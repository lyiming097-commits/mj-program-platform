from __future__ import annotations

from decimal import Decimal
import json
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase

from . import views
from .models import (
    AppPermissionRule,
    ProjectAssignment,
    ProjectMessage,
    ProjectMessageRead,
    ProjectNode,
    ServiceProject,
    ServiceProvider,
    Settlement,
)


class ApiRequestMixin:
    factory: RequestFactory

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        user_id: str = "system-admin",
        name: str = "系统管理员",
        admin: bool = True,
        query: dict | None = None,
    ):
        if method.lower() == "get":
            request = self.factory.get(path, data=query or {})
        elif method.lower() == "patch":
            request = self.factory.patch(
                path,
                data=json.dumps(payload or {}, ensure_ascii=False),
                content_type="application/json",
            )
        else:
            request = self.factory.post(
                path,
                data=json.dumps(payload or {}, ensure_ascii=False),
                content_type="application/json",
            )
        request.auth_user_id = user_id
        request.auth_user_name = name
        request.auth_actor_user_id = user_id
        request.auth_actor_name = name
        request.auth_is_proxy = False
        request.auth_can_use_system_admin = admin
        is_provider = ServiceProvider.objects.filter(auth_user_id=user_id).exists()
        request.auth_token_claims = (
            {"chn": "wechat-mini", "aud": "after-sales-mobile"}
            if not admin and is_provider
            else {"chn": "dingtalk", "aud": "platform"}
        )
        return request

    @staticmethod
    def data(response) -> dict:
        return json.loads(response.content.decode("utf-8"))


class ProjectMessageApiTests(ApiRequestMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        AppPermissionRule.objects.create(permission="sales", scope_type="employee", target_id="message-owner")
        self.provider_a = ServiceProvider.objects.create(
            auth_user_id="message-provider-a",
            name="节点服务员甲",
            role=ServiceProvider.ROLE_INSTALLER,
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        self.provider_b = ServiceProvider.objects.create(
            auth_user_id="message-provider-b",
            name="节点服务员乙",
            role=ServiceProvider.ROLE_SUPPORT,
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        self.outsider = ServiceProvider.objects.create(
            auth_user_id="message-outsider",
            name="项目外人员",
            role=ServiceProvider.ROLE_SUPPORT,
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        self.project = ServiceProject.objects.create(
            code="MSG-MS-001",
            service_type=ServiceProject.TYPE_MIDSALES,
            name="消息权限测试项目",
            customer="测试客户",
            owner_user_id="message-owner",
            owner_name="项目负责人",
            status=ServiceProject.STATUS_IN_PROGRESS,
        )
        self.node_a = ProjectNode.objects.create(
            project=self.project,
            node_key="device-install",
            name="设备安装",
            sequence=1,
            kind="delivery",
            enabled=True,
            status=ProjectNode.STATUS_ACTIVE,
        )
        self.node_b = ProjectNode.objects.create(
            project=self.project,
            node_key="device-debug",
            name="设备调试",
            sequence=2,
            kind="delivery",
            enabled=True,
            status=ProjectNode.STATUS_PENDING,
        )
        self.assignment_a = ProjectAssignment.objects.create(
            project=self.project,
            node=self.node_a,
            provider=self.provider_a,
            status=ProjectAssignment.STATUS_IN_PROGRESS,
        )
        ProjectAssignment.objects.create(
            project=self.project,
            node=self.node_b,
            provider=self.provider_b,
            status=ProjectAssignment.STATUS_ASSIGNED,
        )

    def user_request(self, method, path, payload=None, *, user_id, name, query=None):
        return self.request(
            method,
            path,
            payload,
            user_id=user_id,
            name=name,
            admin=False,
            query=query,
        )

    def send(self, *, user_id, name, content, node_key="", admin=False):
        request = self.request(
            "post",
            f"/api/after-sales/projects/{self.project.id}/messages",
            {"nodeKey": node_key, "content": content},
            user_id=user_id,
            name=name,
            admin=admin,
        )
        return views.project_messages(request, self.project.id)

    def test_project_and_node_conversations_are_isolated_by_participant(self):
        project_message = self.send(
            user_id="message-owner",
            name="项目负责人",
            content="项目级通知",
        )
        self.assertEqual(project_message.status_code, 201, self.data(project_message))
        node_a_message = self.send(
            user_id="system-admin",
            name="系统管理员",
            content="甲节点通知",
            node_key=self.node_a.node_key,
            admin=True,
        )
        self.assertEqual(node_a_message.status_code, 201, self.data(node_a_message))
        node_b_message = self.send(
            user_id="system-admin",
            name="系统管理员",
            content="乙节点通知",
            node_key=self.node_b.node_key,
            admin=True,
        )
        self.assertEqual(node_b_message.status_code, 201, self.data(node_b_message))

        project_rows = views.project_messages(self.user_request(
            "get",
            f"/api/after-sales/projects/{self.project.id}/messages",
            user_id=self.provider_a.auth_user_id,
            name=self.provider_a.name,
        ), self.project.id)
        self.assertEqual(project_rows.status_code, 200, self.data(project_rows))
        self.assertEqual(self.data(project_rows)["unreadCount"], 1)

        node_rows = views.project_messages(self.user_request(
            "get",
            f"/api/after-sales/projects/{self.project.id}/messages",
            user_id=self.provider_a.auth_user_id,
            name=self.provider_a.name,
            query={"nodeKey": self.node_a.node_key},
        ), self.project.id)
        self.assertEqual(node_rows.status_code, 200, self.data(node_rows))
        self.assertEqual([row["content"] for row in self.data(node_rows)["items"]], ["甲节点通知"])

        denied_node = views.project_messages(self.user_request(
            "get",
            f"/api/after-sales/projects/{self.project.id}/messages",
            user_id=self.provider_b.auth_user_id,
            name=self.provider_b.name,
            query={"nodeKey": self.node_a.node_key},
        ), self.project.id)
        self.assertEqual(denied_node.status_code, 404)
        outsider = views.project_messages(self.user_request(
            "get",
            f"/api/after-sales/projects/{self.project.id}/messages",
            user_id=self.outsider.auth_user_id,
            name=self.outsider.name,
        ), self.project.id)
        self.assertEqual(outsider.status_code, 404)

        conversations = views.message_conversations(self.user_request(
            "get",
            "/api/after-sales/messages",
            user_id=self.provider_a.auth_user_id,
            name=self.provider_a.name,
        ))
        self.assertEqual(conversations.status_code, 200, self.data(conversations))
        keys = {row["conversationKey"] for row in self.data(conversations)["items"]}
        self.assertEqual(keys, {"project", self.node_a.node_key})
        self.assertEqual(self.data(conversations)["unreadCount"], 2)

    def test_read_receipts_and_completed_assignment_read_only_history(self):
        project_response = self.send(
            user_id="message-owner",
            name="项目负责人",
            content="请确认项目安排",
        )
        message_id = self.data(project_response)["item"]["id"]
        read_response = views.project_messages_read(self.user_request(
            "post",
            f"/api/after-sales/projects/{self.project.id}/messages/read",
            {"throughId": message_id},
            user_id=self.provider_a.auth_user_id,
            name=self.provider_a.name,
        ), self.project.id)
        self.assertEqual(read_response.status_code, 200, self.data(read_response))
        self.assertEqual(self.data(read_response)["readCount"], 1)
        self.assertEqual(ProjectMessageRead.objects.filter(user_id=self.provider_a.auth_user_id).count(), 1)

        rows = views.project_messages(self.user_request(
            "get",
            f"/api/after-sales/projects/{self.project.id}/messages",
            user_id=self.provider_a.auth_user_id,
            name=self.provider_a.name,
        ), self.project.id)
        self.assertEqual(self.data(rows)["unreadCount"], 0)
        self.assertTrue(self.data(rows)["items"][0]["isRead"])

        self.assignment_a.status = ProjectAssignment.STATUS_COMPLETED
        self.assignment_a.save(update_fields=["status"])
        history = views.project_messages(self.user_request(
            "get",
            f"/api/after-sales/projects/{self.project.id}/messages",
            user_id=self.provider_a.auth_user_id,
            name=self.provider_a.name,
        ), self.project.id)
        self.assertEqual(history.status_code, 200, self.data(history))
        blocked_send = self.send(
            user_id=self.provider_a.auth_user_id,
            name=self.provider_a.name,
            content="完成后不应继续发送",
        )
        self.assertEqual(blocked_send.status_code, 404)
        self.assertEqual(ProjectMessage.objects.count(), 1)

    def test_mobile_home_excludes_presales_tasks_without_message_payload(self):
        self.assignment_a.status = ProjectAssignment.STATUS_COMPLETED
        self.assignment_a.save(update_fields=["status"])
        presales = ServiceProject.objects.create(
            code="MSG-PS-001",
            service_type=ServiceProject.TYPE_PRESALES,
            name="进入移动端的售前交付项目",
            customer="测试客户",
            status=ServiceProject.STATUS_IN_PROGRESS,
        )
        presales_node = ProjectNode.objects.create(
            project=presales,
            node_key="early-plan",
            name="前期方案",
            sequence=1,
            kind="delivery",
            status=ProjectNode.STATUS_ACTIVE,
        )
        ProjectAssignment.objects.create(
            project=presales,
            node=presales_node,
            provider=self.provider_a,
            status=ProjectAssignment.STATUS_IN_PROGRESS,
        )
        self.send(
            user_id="message-owner",
            name="项目负责人",
            content="移动端可见消息",
        )
        ProjectMessage.objects.create(
            project=presales,
            node=presales_node,
            author_user_id="system-admin",
            author_name="系统管理员",
            content="售前交付消息进入移动端",
        )

        response = views.mobile_home(self.user_request(
            "get",
            "/api/after-sales/mobile/home",
            user_id=self.provider_a.auth_user_id,
            name=self.provider_a.name,
        ))
        self.assertEqual(response.status_code, 200, self.data(response))
        payload = self.data(response)
        self.assertEqual(
            {row["project"]["id"] for row in payload["tasks"]},
            {self.project.id},
        )
        completed_task = next(row for row in payload["tasks"] if row["project"]["id"] == self.project.id)
        self.assertEqual(completed_task["assignment"]["status"], ProjectAssignment.STATUS_COMPLETED)
        self.assertNotIn("messages", payload)
        self.assertNotIn("messageUnreadCount", payload)


class SettlementSourceApiTests(ApiRequestMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.provider = ServiceProvider.objects.create(
            auth_user_id="settlement-provider",
            name="结算服务员",
            role=ServiceProvider.ROLE_INSTALLER,
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        self.other_provider = ServiceProvider.objects.create(
            auth_user_id="settlement-provider-other",
            name="其他服务员",
            role=ServiceProvider.ROLE_INSTALLER,
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        self.project = ServiceProject.objects.create(
            code="SET-MS-001",
            service_type=ServiceProject.TYPE_MIDSALES,
            name="结算来源测试项目",
            customer="结算测试客户",
            status=ServiceProject.STATUS_IN_PROGRESS,
        )
        self.valid_node = self.node(
            "construction-work", "工程施工", 1,
            status=ProjectNode.STATUS_COMPLETED,
            estimated_fee=Decimal("1000.00"),
            actual_fee=Decimal("1250.00"),
            business_data={"externalQuote": "1500.00"},
        )
        self.active_node = self.node(
            "device-install", "设备安装", 2,
            status=ProjectNode.STATUS_ACTIVE,
            actual_fee=Decimal("300.00"),
        )
        self.no_fee_node = self.node(
            "device-debug", "设备调试", 3,
            status=ProjectNode.STATUS_COMPLETED,
        )
        self.assignment = ProjectAssignment.objects.create(
            project=self.project,
            node=self.valid_node,
            provider=self.provider,
            status=ProjectAssignment.STATUS_ASSIGNED,
        )
        self.other_assignment = ProjectAssignment.objects.create(
            project=self.project,
            node=self.active_node,
            provider=self.other_provider,
            status=ProjectAssignment.STATUS_COMPLETED,
        )

    def node(self, key, name, sequence, **fields):
        return ProjectNode.objects.create(
            project=self.project,
            node_key=key,
            name=name,
            sequence=sequence,
            kind="delivery",
            enabled=True,
            **fields,
        )

    def create_settlement(self, **overrides):
        payload = {
            "sourceNodeId": self.valid_node.id,
            "sourceAssignmentId": self.assignment.id,
            "bearer": Settlement.BEARER_CUSTOMER,
        }
        payload.update(overrides)
        return views.settlements_collection(self.request(
            "post",
            "/api/after-sales/settlements",
            payload,
        ))

    def test_only_completed_charge_node_with_actual_fee_and_completed_assignment_is_eligible(self):
        active = self.create_settlement(
            sourceNodeId=self.active_node.id,
            sourceAssignmentId=None,
        )
        self.assertEqual(active.status_code, 409)
        self.assertEqual(self.data(active)["code"], "SETTLEMENT_SOURCE_NOT_COMPLETED")

        missing_fee = self.create_settlement(
            sourceNodeId=self.no_fee_node.id,
            sourceAssignmentId=None,
        )
        self.assertEqual(missing_fee.status_code, 409)
        self.assertEqual(self.data(missing_fee)["code"], "SETTLEMENT_SOURCE_FEE_REQUIRED")

        incomplete_assignment = self.create_settlement()
        self.assertEqual(incomplete_assignment.status_code, 409)
        self.assertEqual(
            self.data(incomplete_assignment)["code"],
            "SETTLEMENT_SOURCE_ASSIGNMENT_NOT_COMPLETED",
        )

        mismatched_assignment = self.create_settlement(
            sourceAssignmentId=self.other_assignment.id,
        )
        self.assertEqual(mismatched_assignment.status_code, 409)
        self.assertEqual(
            self.data(mismatched_assignment)["code"],
            "SETTLEMENT_SOURCE_ASSIGNMENT_MISMATCH",
        )

    def test_source_amounts_are_snapshotted_and_active_source_is_unique(self):
        self.assignment.status = ProjectAssignment.STATUS_COMPLETED
        self.assignment.save(update_fields=["status"])
        response = self.create_settlement(
            finalAmount="1250.00",
            orderAmount="1500.00",
            invoiceDueAmount="1500.00",
        )
        self.assertEqual(response.status_code, 201, self.data(response))
        item = self.data(response)["item"]
        self.assertEqual(item["sourceNodeId"], self.valid_node.id)
        self.assertEqual(item["sourceAssignmentId"], self.assignment.id)
        self.assertEqual(item["budgetAmount"], "1000.00")
        self.assertEqual(item["finalAmount"], "1250.00")
        self.assertEqual(item["orderAmount"], "1500.00")
        self.assertEqual(item["invoiceDueAmount"], "1500.00")
        self.assertEqual(item["remainingReceivable"], "1500.00")
        self.assertIn("工程施工", item["serviceContent"])

        duplicate = self.create_settlement()
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.data(duplicate)["code"], "SETTLEMENT_SOURCE_CONFLICT")
        settlement = Settlement.objects.get(pk=item["id"])
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Settlement.objects.create(
                    code="SET-DIRECT-DUPLICATE",
                    project=self.project,
                    source_node=self.valid_node,
                    service_type=self.project.service_type,
                    customer=self.project.customer,
                    bearer=Settlement.BEARER_CUSTOMER,
                    service_content="重复",
                )

        immutable = views.settlement_item(self.request(
            "patch",
            f"/api/after-sales/settlements/{settlement.id}",
            {"sourceNodeId": self.active_node.id, "expectedRevision": 1},
        ), settlement.id)
        self.assertEqual(immutable.status_code, 409)
        self.assertEqual(self.data(immutable)["code"], "SETTLEMENT_SOURCE_IMMUTABLE")

    def test_customer_settlement_requires_external_quote(self):
        self.assignment.status = ProjectAssignment.STATUS_COMPLETED
        self.assignment.save(update_fields=["status"])
        self.valid_node.business_data = {}
        self.valid_node.save(update_fields=["business_data"])

        response = self.create_settlement()

        self.assertEqual(response.status_code, 409, self.data(response))
        self.assertEqual(self.data(response)["code"], "SETTLEMENT_SOURCE_QUOTE_REQUIRED")
        self.assertIn("对外报价", self.data(response)["error"])

    def test_company_settlement_without_external_quote_uses_actual_cost(self):
        self.assignment.status = ProjectAssignment.STATUS_COMPLETED
        self.assignment.save(update_fields=["status"])
        self.valid_node.business_data = {}
        self.valid_node.save(update_fields=["business_data"])

        response = self.create_settlement(bearer=Settlement.BEARER_COMPANY)

        self.assertEqual(response.status_code, 201, self.data(response))
        self.assertEqual(self.data(response)["item"]["finalAmount"], "1250.00")
        self.assertEqual(self.data(response)["item"]["orderAmount"], "1250.00")

    def test_sources_listing_cancel_and_financial_fields_do_not_block_service_settlement(self):
        self.assignment.status = ProjectAssignment.STATUS_COMPLETED
        self.assignment.save(update_fields=["status"])
        available = views.settlement_sources(self.request(
            "get",
            "/api/after-sales/settlement-sources",
        ))
        self.assertEqual(available.status_code, 200, self.data(available))
        self.assertIn(self.valid_node.id, {row["sourceNodeId"] for row in self.data(available)["items"]})

        created = self.create_settlement()
        settlement_id = self.data(created)["item"]["id"]
        processing = views.settlement_sources(self.request(
            "get",
            "/api/after-sales/settlement-sources",
            query={"state": "processing", "projectId": self.project.id},
        ))
        self.assertEqual([row["settlementId"] for row in self.data(processing)["items"]], [settlement_id])
        cancelled = views.settlement_item(self.request(
            "patch",
            f"/api/after-sales/settlements/{settlement_id}",
            {"status": Settlement.STATUS_CANCELLED, "expectedRevision": 1, "correctionReason": "撤销测试草稿"},
        ), settlement_id)
        self.assertEqual(cancelled.status_code, 200, self.data(cancelled))
        replacement = self.create_settlement(code="SET-REPLACEMENT")
        self.assertEqual(replacement.status_code, 201, self.data(replacement))

        replacement_id = self.data(replacement)["item"]["id"]
        pending = views.settlement_item(self.request(
            "patch",
            f"/api/after-sales/settlements/{replacement_id}",
            {"status": Settlement.STATUS_PENDING, "expectedRevision": 1},
        ), replacement_id)
        self.assertEqual(pending.status_code, 200, self.data(pending))
        settled = views.settlement_item(self.request(
            "patch",
            f"/api/after-sales/settlements/{replacement_id}",
            {"status": Settlement.STATUS_SETTLED, "receivedAmount": "1500.00", "expectedRevision": 2},
        ), replacement_id)
        self.assertEqual(settled.status_code, 200, self.data(settled))
        self.assertEqual(self.data(settled)["item"]["status"], Settlement.STATUS_SETTLED)

    def test_customer_settlement_cannot_close_with_unpaid_amount(self):
        self.assignment.status = ProjectAssignment.STATUS_COMPLETED
        self.assignment.save(update_fields=["status"])
        created = self.create_settlement()
        settlement_id = self.data(created)["item"]["id"]

        blocked = views.settlement_item(self.request(
            "patch",
            f"/api/after-sales/settlements/{settlement_id}",
            {"status": Settlement.STATUS_SETTLED, "expectedRevision": 1},
        ), settlement_id)
        self.assertEqual(blocked.status_code, 409, self.data(blocked))
        self.assertEqual(self.data(blocked)["code"], "SETTLEMENT_RECEIPT_INCOMPLETE")
        self.assertIn("还需收款￥1500.00", self.data(blocked)["error"])

        settled = views.settlement_item(self.request(
            "patch",
            f"/api/after-sales/settlements/{settlement_id}",
            {"status": Settlement.STATUS_SETTLED, "receivedAmount": "1500.00", "expectedRevision": 1},
        ), settlement_id)
        self.assertEqual(settled.status_code, 200, self.data(settled))
        self.assertEqual(self.data(settled)["item"]["status"], Settlement.STATUS_SETTLED)

    @patch("after_sales_api.settlement_finance.get_auth_company_entities", return_value=[
        {"id": 1, "companyName": "迈杰科技有限公司"}, {"id": 2, "companyName": "浙江区域服务部"},
    ])
    def test_company_settlement_persists_detail_fields_and_related_project(self, _directory):
        self.assignment.status = ProjectAssignment.STATUS_COMPLETED
        self.assignment.save(update_fields=["status"])
        related_project = ServiceProject.objects.create(
            code="SET-RELATED-001",
            service_type=ServiceProject.TYPE_MIDSALES,
            name="费用归集关联项目",
            customer="关联客户",
            status=ServiceProject.STATUS_IN_PROGRESS,
        )
        created = self.create_settlement(
            bearer=Settlement.BEARER_COMPANY,
            relatedProjectId=related_project.id,
            subjectType="company",
            subjectName="迈杰科技有限公司",
            subjectId="1",
            remark="初始归集说明",
        )
        self.assertEqual(created.status_code, 201, self.data(created))
        settlement_id = self.data(created)["item"]["id"]

        updated = views.settlement_item(self.request(
            "patch",
            f"/api/after-sales/settlements/{settlement_id}",
            {
                "relatedProjectId": related_project.id,
                "subjectType": "company",
                "subjectName": "浙江区域服务部",
                "subjectId": "2",
                "expectedRevision": 1,
                "remark": "自动保存后的归集说明",
            },
        ), settlement_id)

        self.assertEqual(updated.status_code, 200, self.data(updated))
        item = self.data(updated)["item"]
        self.assertEqual(item["relatedProjectId"], related_project.id)
        self.assertEqual(item["relatedProjectName"], "费用归集关联项目")
        self.assertEqual(item["subjectName"], "浙江区域服务部")
        self.assertEqual(item["remark"], "自动保存后的归集说明")
