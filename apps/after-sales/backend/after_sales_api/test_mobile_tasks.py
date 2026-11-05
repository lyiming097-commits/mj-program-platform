from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from django.test import RequestFactory, TestCase
from django.utils import timezone

from . import mobile_task_views, services, views
from .models import (
    AppPermissionRule,
    ProjectAssignment,
    ProjectEvent,
    ProjectNode,
    ServiceProject,
    ServiceProvider,
)


class MobileTaskUpdateTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        AppPermissionRule.objects.all().delete()
        self.provider = ServiceProvider.objects.create(
            auth_user_id="field-provider",
            name="现场人员",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        self.outsider = ServiceProvider.objects.create(
            auth_user_id="field-outsider",
            name="其他人员",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        self.project = ServiceProject.objects.create(
            code="MOBILE-MS-001",
            service_type=ServiceProject.TYPE_MIDSALES,
            name="移动现场项目",
            customer="测试客户",
            status=ServiceProject.STATUS_IN_PROGRESS,
            current_node_key="device-debug",
        )
        self.node = ProjectNode.objects.create(
            project=self.project,
            node_key="device-debug",
            name="设备调试",
            sequence=1,
            status=ProjectNode.STATUS_ACTIVE,
            actual_start_at=datetime.fromisoformat("2026-07-30T09:15:00+00:00"),
        )
        self.assignment = ProjectAssignment.objects.create(
            project=self.project,
            node=self.node,
            provider=self.provider,
            status=ProjectAssignment.STATUS_ASSIGNED,
            planned_start_date=date(2026, 9, 3),
            standard_duration="3 天",
            note="完成设备联调并核对现场网络条件",
        )

    def authenticated(self, request, user_id: str, *, admin: bool = False):
        request.auth_user_id = user_id
        request.auth_user_name = user_id
        request.auth_actor_user_id = user_id
        request.auth_actor_name = user_id
        request.auth_is_proxy = False
        request.auth_can_use_system_admin = admin
        request.auth_token_claims = (
            {"chn": "dingtalk", "aud": "platform"}
            if admin
            else {"chn": "wechat-mini", "aud": "after-sales-mobile"}
        )
        return request

    @staticmethod
    def data(response) -> dict:
        return json.loads(response.content.decode("utf-8"))

    def update(self, assignment_id: int, payload: dict, user_id: str):
        request = self.authenticated(
            self.factory.patch(
                f"/api/after-sales/mobile/tasks/{assignment_id}",
                data=json.dumps(payload, ensure_ascii=False),
                content_type="application/json",
            ),
            user_id,
        )
        return mobile_task_views.mobile_task_update(request, assignment_id)

    def assign(self, provider: ServiceProvider):
        request = self.authenticated(self.factory.post("/api/after-sales/projects/assignments"), "admin-user", admin=True)
        return services.assign_provider(request, self.project.id, node_key=self.node.node_key, provider_id=provider.id)

    def mobile_home(self, provider: ServiceProvider):
        request = self.authenticated(self.factory.get("/api/after-sales/mobile/home"), provider.auth_user_id)
        return self.data(views.mobile_home(request))

    def test_reassignment_keeps_previous_draft_but_clears_current_execution(self):
        self.assertEqual(self.update(self.assignment.id, {
            "draft": True, "actualEndAt": "2026-07-30T10:15:00+00:00",
            "actualFee": "85", "actualFeeNote": "旧费用", "note": "旧备注",
        }, self.provider.auth_user_id).status_code, 200)
        replacement = self.assign(self.outsider)

        self.assignment.refresh_from_db()
        self.node.refresh_from_db()
        self.assertEqual(self.assignment.status, ProjectAssignment.STATUS_CANCELLED)
        self.assertIsNone(self.node.actual_end_at)
        self.assertIsNone(self.node.actual_fee)
        self.assertNotIn("feeActualNote", self.node.business_data)
        self.assertNotIn("actualDuration", self.node.business_data)
        self.assertEqual(self.node.business_data["fieldDrafts"][str(self.assignment.id)]["note"], "旧备注")
        self.assertEqual(self.mobile_home(self.provider)["tasks"], [])
        task = self.mobile_home(self.outsider)["tasks"][0]
        self.assertEqual(task["assignment"]["id"], replacement.id)
        self.assertEqual(task["node"]["actualEndAt"], "")
        self.assertEqual(task["node"]["actualFee"], "")
        self.assertNotIn("fieldDrafts", task["node"]["businessData"])
        self.assertNotIn("fieldDrafts", task["nodes"][0]["businessData"])
        self.assertEqual(self.data(self.update(self.assignment.id, {"draft": True}, self.provider.auth_user_id))["code"], "MOBILE_TASK_READ_ONLY")

    def test_reassignment_does_not_use_old_submission_for_settlement_or_returning_provider(self):
        response = self.update(self.assignment.id, {
            "actualEndAt": "2026-07-30T10:15:00+00:00", "actualFee": "85",
            "submitted": True,
        }, self.provider.auth_user_id)
        self.assertEqual(response.status_code, 200, self.data(response))
        replacement = self.assign(self.outsider)
        self.node.refresh_from_db()
        self.assertFalse(services.field_completion_submitted(self.node))
        self.assertTrue(self.node.business_data["fieldSubmissions"][str(self.assignment.id)]["submitted"])
        self.assertNotIn("fieldSubmissions", self.mobile_home(self.outsider)["tasks"][0]["node"]["businessData"])
        response = self.update(replacement.id, {"draft": True, "actualFee": "20"}, self.outsider.auth_user_id)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.node.refresh_from_db()
        self.assertEqual(services.unsettled_settlement_nodes(self.project, [self.node]), [])

        returning = self.assign(self.provider)
        self.node.refresh_from_db()
        self.assertEqual(returning.id, self.assignment.id)
        self.assertNotIn(str(self.assignment.id), self.node.business_data.get("fieldSubmissions", {}))
        self.assertFalse(services.field_completion_submitted(self.node))
        self.assertFalse(self.mobile_home(self.provider)["tasks"][0]["node"]["businessData"].get("fieldSubmissions"))
        event = ProjectEvent.objects.filter(event_type="provider_assigned").latest("id")
        self.assertTrue(event.before_values["previousAssignmentRecord"]["fieldSubmissions"]["submitted"])

    def test_legacy_aftersales_reassignment_is_masked_in_mobile_responses(self):
        self.project.service_type = ServiceProject.TYPE_AFTERSALES
        self.project.current_node_key = "onsite-service"
        self.project.save(update_fields=["service_type", "current_node_key"])
        self.node.node_key = "onsite-service"
        self.node.save(update_fields=["node_key"])
        replacement = self.assign(self.outsider)
        self.node.actual_end_at = datetime.fromisoformat("2026-07-30T10:15:00+00:00")
        self.node.actual_fee = "85"
        self.node.business_data = {
            "fieldSubmissions": {str(self.assignment.id): {"submitted": True, "note": "旧人员提交"}},
            "feeActualNote": "旧费用", "actualDuration": "0天1小时0分钟",
        }
        self.node.save(update_fields=["actual_end_at", "actual_fee", "business_data"])

        task = self.mobile_home(self.outsider)["tasks"][0]
        self.assertEqual(task["node"]["actualEndAt"], "")
        self.assertEqual(task["node"]["actualFee"], "")
        self.assertNotIn("feeActualNote", task["node"]["businessData"])
        self.assertNotIn("fieldSubmissions", task["node"]["businessData"])
        self.assertNotIn("fieldSubmissions", task["nodes"][0]["businessData"])
        response = self.update(replacement.id, {"draft": True, "actualFee": "20"}, self.outsider.auth_user_id)
        self.assertEqual(response.status_code, 200, self.data(response))
        response_node = self.data(response)["item"]["node"]
        self.assertEqual(set(response_node["businessData"]["fieldDrafts"]), {str(replacement.id)})
        self.assertEqual(response_node["actualEndAt"], "")
        self.assertEqual(response_node["actualFee"], "20.00")
        self.assertEqual(response_node["businessData"]["actualDuration"], "")
        self.assertNotIn("feeActualNote", response_node["businessData"])
        self.assertNotIn("fieldSubmissions", self.data(response)["item"]["node"]["businessData"])
        incomplete = self.update(replacement.id, {"submitted": True, "actualFee": "20"}, self.outsider.auth_user_id)
        self.assertEqual(self.data(incomplete)["code"], "MOBILE_COMPLETION_INCOMPLETE")

    def test_assigned_provider_submits_actual_execution_without_closing_node(self):
        draft_response = self.update(self.assignment.id, {
            "draft": True,
            "actualEndAt": "2026-07-30T10:00:00+00:00",
            "actualFee": "600.00",
            "actualFeeNote": "现场先填费用",
            "note": "现场先填备注",
        }, self.provider.auth_user_id)
        self.assertEqual(draft_response.status_code, 200, self.data(draft_response))
        self.node.refresh_from_db()
        self.assertEqual(str(self.node.actual_fee), "600.00")
        self.assertEqual(self.node.business_data["feeActualNote"], "现场先填费用")
        self.assertEqual(self.node.business_data["actualStartTime"], self.node.actual_start_at.isoformat())
        self.assertEqual(self.node.business_data["actualEndTime"], self.node.actual_end_at.isoformat())
        self.assertEqual(self.node.business_data["actualDuration"], "0天0小时45分钟")
        self.assertEqual(self.node.business_data["fieldDrafts"][str(self.assignment.id)]["note"], "现场先填备注")

        management_request = self.authenticated(
            self.factory.get(f"/api/after-sales/projects/{self.project.id}"),
            "admin-user",
            admin=True,
        )
        management_response = views.project_item(management_request, self.project.id)
        self.assertEqual(management_response.status_code, 200)
        management_node = next(
            item for item in self.data(management_response)["item"]["nodes"]
            if item["nodeKey"] == self.node.node_key
        )
        self.assertEqual(management_node["actualFee"], "600.00")
        self.assertEqual(management_node["businessData"]["actualDuration"], "0天0小时45分钟")
        self.assertEqual(management_node["businessData"]["feeActualNote"], "现场先填费用")

        response = self.update(self.assignment.id, {
            "actualStartAt": "2026-07-30T09:15:00+00:00",
            "actualEndAt": "2026-07-30T11:00:00+00:00",
            "actualFee": "680.50",
            "actualFeeNote": "现场交通及辅材费用",
            "actualDuration": "999天",
            "settlementEligible": True,
            "note": "客户已现场确认",
            "submitted": True,
        }, self.provider.auth_user_id)
        self.assertEqual(response.status_code, 200)
        self.node.refresh_from_db()
        self.assignment.refresh_from_db()
        self.assertEqual(str(self.node.actual_fee), "680.50")
        self.assertEqual(self.node.actual_start_at.isoformat(), "2026-07-30T09:15:00+00:00")
        self.assertEqual(self.node.status, ProjectNode.STATUS_ACTIVE)
        self.assertTrue(self.node.business_data["settlementEligible"])
        self.assertEqual(self.node.business_data["actualDuration"], "0天1小时45分钟")
        self.assertEqual(self.node.business_data["feeActualNote"], "现场交通及辅材费用")
        self.assertNotIn(str(self.assignment.id), self.node.business_data.get("fieldDrafts", {}))
        submission = self.node.business_data["fieldSubmissions"][str(self.assignment.id)]
        self.assertTrue(submission["submitted"])
        self.assertEqual(submission["providerId"], self.provider.id)
        self.assertEqual(submission["actualDuration"], "0天1小时45分钟")
        self.assertEqual(submission["actualFeeNote"], "现场交通及辅材费用")
        self.assertEqual(submission["note"], "客户已现场确认")
        self.assertEqual(self.assignment.note, "完成设备联调并核对现场网络条件")
        self.assertEqual(self.assignment.status, ProjectAssignment.STATUS_COMPLETED)
        self.assertIsNotNone(self.assignment.completed_at)
        self.assertTrue(ProjectEvent.objects.filter(event_type="field_completion_submitted").exists())

    def test_end_time_in_same_displayed_minute_as_management_start_is_allowed(self):
        self.node.actual_start_at = datetime.fromisoformat("2026-07-30T09:15:45+00:00")
        self.node.save(update_fields=["actual_start_at"])
        response = self.update(self.assignment.id, {
            "actualEndAt": "2026-07-30T09:15:00+00:00",
            "actualFee": "100.00",
            "submitted": True,
        }, self.provider.auth_user_id)

        self.assertEqual(response.status_code, 200, self.data(response))
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["actualDuration"], "0天0小时0分钟")

    def test_management_can_advance_after_same_minute_field_completion(self):
        self.node.actual_start_at = datetime.fromisoformat("2026-07-30T09:15:45+00:00")
        self.node.save(update_fields=["actual_start_at"])
        submitted = self.update(self.assignment.id, {
            "actualEndAt": "2026-07-30T09:15:00+00:00",
            "actualFee": "0",
            "submitted": True,
        }, self.provider.auth_user_id)
        self.assertEqual(submitted.status_code, 200, self.data(submitted))

        management_request = self.authenticated(
            self.factory.post(
                f"/api/after-sales/projects/{self.project.id}/advance",
                data=json.dumps({"nodeKey": self.node.node_key}),
                content_type="application/json",
            ),
            "admin-user",
            admin=True,
        )
        response = views.project_advance(management_request, self.project.id)
        self.assertEqual(response.status_code, 200, self.data(response))

    def test_unconfirmed_payload_does_not_overwrite_management_start_time(self):
        response = self.update(self.assignment.id, {
            "actualStartAt": "2026-09-02T10:30:00+08:00",
            "submitted": False,
        }, self.provider.auth_user_id)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.data(response)["code"], "MOBILE_COMPLETION_CONFIRM_REQUIRED")
        self.node.refresh_from_db()
        self.assertEqual(self.node.actual_start_at.isoformat(), "2026-07-30T09:15:00+00:00")
        self.assertNotIn("fieldSubmissions", self.node.business_data)

    def test_outsider_and_completed_assignment_cannot_update(self):
        response = self.update(self.assignment.id, {"actualFee": 1}, self.outsider.auth_user_id)
        self.assertEqual(response.status_code, 404)
        self.assignment.status = ProjectAssignment.STATUS_COMPLETED
        self.assignment.save(update_fields=["status"])
        response = self.update(self.assignment.id, {"actualFee": 1}, self.provider.auth_user_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.data(response)["code"], "MOBILE_TASK_READ_ONLY")

    def test_completion_requires_actual_fee(self):
        response = self.update(self.assignment.id, {
            "actualStartAt": "2026-07-30T09:15:00+00:00",
            "actualEndAt": "2026-07-30T11:00:00+00:00",
            "submitted": True,
        }, self.provider.auth_user_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.data(response)["code"], "MOBILE_COMPLETION_INCOMPLETE")
        self.assertIn("实际费用", self.data(response)["error"])

    def test_aftersales_submit_requires_service_fields_without_attachments(self):
        aftersales = ServiceProject.objects.create(
            code="MOBILE-AS-001",
            service_type=ServiceProject.TYPE_AFTERSALES,
            name="售后现场项目",
            customer="售后客户",
            status=ServiceProject.STATUS_IN_PROGRESS,
            current_node_key="onsite-service",
        )
        node = ProjectNode.objects.create(
            project=aftersales,
            node_key="onsite-service",
            name="上门售后",
            sequence=1,
            status=ProjectNode.STATUS_ACTIVE,
            actual_start_at=timezone.now(),
        )
        assignment = ProjectAssignment.objects.create(
            project=aftersales,
            node=node,
            provider=self.provider,
            status=ProjectAssignment.STATUS_ASSIGNED,
        )
        payload = {
            "actualStartAt": node.actual_start_at.isoformat(),
            "actualEndAt": (node.actual_start_at + timedelta(hours=3)).isoformat(),
            "actualDuration": "任意手工值",
            "actualFee": "100.00",
            "submitted": True,
        }
        response = self.update(assignment.id, payload, self.provider.auth_user_id)
        self.assertEqual(response.status_code, 200)
        node.refresh_from_db()
        self.assertEqual(node.business_data["actualDuration"], "0天3小时0分钟")
        self.assertNotIn("completionRecords", node.business_data)
        self.assertEqual(node.status, ProjectNode.STATUS_ACTIVE)
        self.assertEqual(node.business_data["managerReviewStatus"], "submitted")

        rejected = self.authenticated(
            self.factory.post(
                f"/api/after-sales/projects/{aftersales.id}/reject-completion",
                data=json.dumps({"nodeKey": node.node_key, "note": "请补充清晰照片"}),
                content_type="application/json",
            ),
            "admin-user",
            admin=True,
        )
        response = views.project_reject_completion(rejected, aftersales.id)
        self.assertEqual(response.status_code, 200, self.data(response))
        node.refresh_from_db()
        assignment.refresh_from_db()
        submission = node.business_data["fieldSubmissions"][str(assignment.id)]
        self.assertFalse(submission["submitted"])
        self.assertEqual(submission["rejectedReason"], "请补充清晰照片")
        self.assertEqual(assignment.status, ProjectAssignment.STATUS_IN_PROGRESS)
        self.assertIsNone(assignment.completed_at)

    def test_admin_cannot_advance_field_node_until_provider_confirms_completion(self):
        request = self.authenticated(
            self.factory.post(
                f"/api/after-sales/projects/{self.project.id}/advance",
                data=json.dumps({"nodeKey": self.node.node_key}),
                content_type="application/json",
            ),
            "admin-user",
            admin=True,
        )
        response = views.project_advance(request, self.project.id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.data(response)["code"], "FIELD_COMPLETION_REQUIRED")

        response = self.update(self.assignment.id, {
            "actualStartAt": "2026-07-30T09:15:00+00:00",
            "actualEndAt": "2026-07-30T11:00:00+00:00",
            "actualFee": "0",
            "submitted": True,
        }, self.provider.auth_user_id)
        self.assertEqual(response.status_code, 200)

        request = self.authenticated(
            self.factory.post(
                f"/api/after-sales/projects/{self.project.id}/advance",
                data=json.dumps({"nodeKey": self.node.node_key}),
                content_type="application/json",
            ),
            "admin-user",
            admin=True,
        )
        response = views.project_advance(request, self.project.id)
        self.assertEqual(response.status_code, 200)

    def test_aftersales_admin_autosave_cannot_overwrite_field_execution_values(self):
        aftersales = ServiceProject.objects.create(
            code="MOBILE-AS-OWNERSHIP",
            service_type=ServiceProject.TYPE_AFTERSALES,
            name="售后字段归属",
            customer="售后客户",
            status=ServiceProject.STATUS_IN_PROGRESS,
            current_node_key="onsite-service",
        )
        node = ProjectNode.objects.create(
            project=aftersales,
            node_key="onsite-service",
            name="上门售后",
            sequence=1,
            status=ProjectNode.STATUS_ACTIVE,
            actual_start_at=timezone.now(),
            actual_end_at=timezone.now(),
            actual_fee="88.00",
            business_data={
                "actualDuration": "0天1小时0分钟",
                "feeActualNote": "现场填写",
                "fieldSubmissions": {"1": {"submitted": True}},
            },
        )
        request = self.authenticated(
            self.factory.patch(
                f"/api/after-sales/projects/{aftersales.id}/nodes/{node.node_key}",
                data=json.dumps({
                    "actualStartAt": "2000-01-01T00:00:00+00:00",
                    "actualEndAt": "2000-01-02T00:00:00+00:00",
                    "actualFee": "999.00",
                    "businessData": {
                        "actualDuration": "错误值",
                        "feeActualNote": "管理端覆盖",
                        "fieldSubmissions": {},
                        "feeEstimatedNote": "管理端预计备注",
                    },
                }),
                content_type="application/json",
            ),
            "admin-user",
            admin=True,
        )
        response = views.project_node_autosave(request, aftersales.id, node.node_key)
        self.assertEqual(response.status_code, 200, self.data(response))
        node.refresh_from_db()
        self.assertEqual(str(node.actual_fee), "88.00")
        self.assertEqual(node.business_data["actualDuration"], "0天1小时0分钟")
        self.assertEqual(node.business_data["feeActualNote"], "现场填写")
        self.assertTrue(node.business_data["fieldSubmissions"]["1"]["submitted"])
        self.assertEqual(node.business_data["feeEstimatedNote"], "管理端预计备注")

    def test_midsales_admin_autosave_cannot_overwrite_field_execution_values(self):
        self.node.actual_end_at = datetime.fromisoformat("2026-07-30T10:15:00+00:00")
        self.node.actual_fee = "88.00"
        self.node.business_data = {
            "actualStartTime": self.node.actual_start_at.isoformat(),
            "actualEndTime": self.node.actual_end_at.isoformat(),
            "actualDuration": "0天1小时0分钟",
            "feeActualNote": "现场填写",
            "fieldDrafts": {str(self.assignment.id): {"note": "现场草稿"}},
            "fieldSubmissions": {str(self.assignment.id): {"submitted": True}},
        }
        self.node.save(update_fields=["actual_end_at", "actual_fee", "business_data"])
        request = self.authenticated(
            self.factory.patch(
                f"/api/after-sales/projects/{self.project.id}/nodes/{self.node.node_key}",
                data=json.dumps({
                    "actualStartAt": "2000-01-01T00:00:00+00:00",
                    "actualEndAt": "2000-01-02T00:00:00+00:00",
                    "actualFee": "999.00",
                    "businessData": {
                        "actualStartTime": "错误开始时间",
                        "actual_start_time": "错误开始时间（下划线）",
                        "actualEndTime": "错误结束时间",
                        "actual_end_time": "错误结束时间（下划线）",
                        "actualDuration": "错误时长",
                        "actual_duration": "错误时长（下划线）",
                        "feeActualNote": "管理端覆盖",
                        "fee_actual_note": "管理端覆盖（下划线）",
                        "fieldDrafts": {},
                        "field_drafts": {},
                        "fieldSubmissions": {},
                        "field_submissions": {},
                        "feeEstimatedNote": "管理端预计备注",
                    },
                }),
                content_type="application/json",
            ),
            "admin-user",
            admin=True,
        )
        response = views.project_node_autosave(request, self.project.id, self.node.node_key)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.node.refresh_from_db()
        self.assertEqual(str(self.node.actual_fee), "88.00")
        self.assertEqual(self.node.actual_start_at.isoformat(), "2026-07-30T09:15:00+00:00")
        self.assertEqual(self.node.actual_end_at.isoformat(), "2026-07-30T10:15:00+00:00")
        self.assertEqual(self.node.business_data["actualStartTime"], "2026-07-30T09:15:00+00:00")
        self.assertEqual(self.node.business_data["actualEndTime"], "2026-07-30T10:15:00+00:00")
        self.assertEqual(self.node.business_data["actualDuration"], "0天1小时0分钟")
        self.assertEqual(self.node.business_data["feeActualNote"], "现场填写")
        self.assertEqual(self.node.business_data["fieldDrafts"][str(self.assignment.id)]["note"], "现场草稿")
        self.assertTrue(self.node.business_data["fieldSubmissions"][str(self.assignment.id)]["submitted"])
        self.assertEqual(self.node.business_data["feeEstimatedNote"], "管理端预计备注")

    def test_provider_cannot_use_admin_project_endpoints(self):
        request = self.authenticated(
            self.factory.get("/api/after-sales/projects"),
            self.provider.auth_user_id,
        )
        response = views.projects_collection(request)
        self.assertEqual(response.status_code, 403)

        request = self.authenticated(
            self.factory.post(
                f"/api/after-sales/projects/{self.project.id}/advance",
                data=json.dumps({"nodeKey": self.node.node_key}),
                content_type="application/json",
            ),
            self.provider.auth_user_id,
        )
        response = views.project_advance(request, self.project.id)
        self.assertEqual(response.status_code, 403)

    def test_deleted_project_disappears_from_management_and_mobile_tasks(self):
        mobile_request = self.authenticated(
            self.factory.get("/api/after-sales/mobile/home"),
            self.provider.auth_user_id,
        )
        before = views.mobile_home(mobile_request)
        self.assertIn(
            self.project.id,
            {item["project"]["id"] for item in self.data(before)["tasks"]},
        )

        delete_request = self.authenticated(
            self.factory.delete(f"/api/after-sales/projects/{self.project.id}"),
            "admin-user",
            admin=True,
        )
        deleted = views.project_item(delete_request, self.project.id)
        self.assertEqual(deleted.status_code, 200, self.data(deleted))

        mobile_request = self.authenticated(
            self.factory.get("/api/after-sales/mobile/home"),
            self.provider.auth_user_id,
        )
        after = views.mobile_home(mobile_request)
        self.assertNotIn(
            self.project.id,
            {item["project"]["id"] for item in self.data(after)["tasks"]},
        )
        management_request = self.authenticated(
            self.factory.get("/api/after-sales/projects", {"type": "midsales"}),
            "admin-user",
            admin=True,
        )
        management = views.projects_collection(management_request)
        self.assertNotIn(self.project.id, {item["id"] for item in self.data(management)["items"]})

    def test_mobile_home_excludes_mail_service_tasks(self):
        self.node.business_data = {"deliveryNote": "管理端处理说明"}
        self.node.save(update_fields=["business_data"])
        mail_project = ServiceProject.objects.create(
            code="MOBILE-AS-MAIL",
            service_type=ServiceProject.TYPE_AFTERSALES,
            name="寄件售后",
            customer="寄件客户",
            status=ServiceProject.STATUS_IN_PROGRESS,
            current_node_key="mail-service",
        )
        mail_node = ProjectNode.objects.create(
            project=mail_project,
            node_key="mail-service",
            name="寄件售后",
            sequence=1,
            status=ProjectNode.STATUS_ACTIVE,
        )
        ProjectAssignment.objects.create(
            project=mail_project,
            node=mail_node,
            provider=self.provider,
            status=ProjectAssignment.STATUS_ASSIGNED,
        )
        request = self.authenticated(
            self.factory.get("/api/after-sales/mobile/home"),
            self.provider.auth_user_id,
        )
        response = views.mobile_home(request)
        self.assertEqual(response.status_code, 200)
        tasks = self.data(response)["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["node"]["settlementStatus"], "unconfirmed")
        self.assertEqual(tasks[0]["assignment"]["plannedStartDate"], "2026-09-03")
        self.assertEqual(tasks[0]["assignment"]["standardDuration"], "3 天")
        self.assertEqual(tasks[0]["assignment"]["note"], "完成设备联调并核对现场网络条件")
        self.assertEqual(tasks[0]["node"]["businessData"]["deliveryNote"], "管理端处理说明")

    def test_presales_delivery_is_not_exposed_to_field_workers(self):
        presales = ServiceProject.objects.create(
            code="MOBILE-PS-001",
            service_type=ServiceProject.TYPE_PRESALES,
            name="售前不进入现场端",
            customer="售前客户",
            status=ServiceProject.STATUS_IN_PROGRESS,
            current_node_key="early-plan",
        )
        ProjectNode.objects.create(
            project=presales,
            node_key="early-approval",
            name="前期立项",
            sequence=1,
            kind="approval",
            status=ProjectNode.STATUS_COMPLETED,
            business_data={"outcome": "approved", "outcomeLabel": "立项成功"},
        )
        node = ProjectNode.objects.create(
            project=presales,
            node_key="early-plan",
            name="前期方案",
            sequence=2,
            kind="delivery",
            status=ProjectNode.STATUS_ACTIVE,
        )
        ProjectAssignment.objects.create(
            project=presales,
            node=node,
            provider=self.provider,
            status=ProjectAssignment.STATUS_IN_PROGRESS,
            planned_start_date=date(2026, 9, 3),
            standard_duration="3 天",
        )
        start_request = self.authenticated(
            self.factory.post(
                f"/api/after-sales/projects/{presales.id}/start",
                data=json.dumps({"nodeKey": node.node_key}),
                content_type="application/json",
            ),
            "admin-user",
            admin=True,
        )
        started = views.project_start(start_request, presales.id)
        self.assertEqual(started.status_code, 200, self.data(started))
        request = self.authenticated(
            self.factory.get("/api/after-sales/mobile/home"),
            self.provider.auth_user_id,
        )
        response = views.mobile_home(request)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertNotIn(presales.id, {row["project"]["id"] for row in self.data(response)["tasks"]})

    def test_presales_delivery_cannot_be_updated_by_field_workers(self):
        presales = ServiceProject.objects.create(
            code="MOBILE-PS-FLOW",
            service_type=ServiceProject.TYPE_PRESALES,
            name="售前现场闭环",
            customer="售前客户",
            status=ServiceProject.STATUS_IN_PROGRESS,
            current_node_key="early-plan",
        )
        ProjectNode.objects.create(
            project=presales,
            node_key="early-approval",
            name="前期立项",
            sequence=1,
            kind="approval",
            status=ProjectNode.STATUS_COMPLETED,
            business_data={"outcome": "approved", "outcomeLabel": "立项成功"},
        )
        node = ProjectNode.objects.create(
            project=presales,
            node_key="early-plan",
            name="前期方案",
            sequence=2,
            kind="delivery",
            status=ProjectNode.STATUS_ACTIVE,
        )
        assignment = ProjectAssignment.objects.create(
            project=presales,
            node=node,
            provider=self.provider,
            status=ProjectAssignment.STATUS_ASSIGNED,
            planned_start_date=date(2026, 9, 3),
            standard_duration="3 天",
        )

        start_request = self.authenticated(
            self.factory.post(
                f"/api/after-sales/projects/{presales.id}/start",
                data=json.dumps({"nodeKey": node.node_key}),
                content_type="application/json",
            ),
            "admin-user",
            admin=True,
        )
        started = views.project_start(start_request, presales.id)
        self.assertEqual(started.status_code, 200, self.data(started))
        node.refresh_from_db()
        blocked = self.update(assignment.id, {
            "draft": True,
            "actualEndAt": (node.actual_start_at + timedelta(hours=2)).isoformat(),
        }, self.provider.auth_user_id)
        self.assertEqual(blocked.status_code, 404, self.data(blocked))
        self.assertEqual(self.data(blocked)["code"], "MOBILE_TASK_NOT_FOUND")
