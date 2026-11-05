from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import json
from unittest.mock import patch

from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from . import services, views
from .models import (
    AppPermissionRule,
    FieldFeedback,
    PrivateAttachment,
    ProjectAssignment,
    ProjectEvent,
    ProjectNode,
    Reward,
    RewardPrize,
    ServiceProject,
    ServiceProvider,
    ServiceRating,
    ServiceResource,
    ServiceTicket,
    Settlement,
    SettlementEvent,
    TicketMessage,
    WorkflowCase,
)
from .platform import SameOriginWriteMiddleware


AFTERSALES_DISPATCH_DATA = {
    "managerContact": "13800000000",
    "expectedDuration": "1天",
    "feeAgreement": "客户承担",
    "feeRemark": "按实际服务结算",
    "products": [{
        "name": "迈杰智能讲台",
        "quantity": 1,
        "carryNeed": "需要",
        "installNeed": "需要",
        "debugNeed": "需要",
    }],
}


class RequestMixin:
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
        proxy: bool = False,
        query: dict | None = None,
    ):
        method = method.lower()
        if method == "get":
            request = self.factory.get(path, data=query or {})
        elif method == "patch":
            request = self.factory.patch(path, data=json.dumps(payload or {}, ensure_ascii=False), content_type="application/json")
        elif method == "delete":
            request = self.factory.delete(path, data=json.dumps(payload or {}, ensure_ascii=False), content_type="application/json")
        else:
            request = self.factory.post(path, data=json.dumps(payload or {}, ensure_ascii=False), content_type="application/json")
        request.auth_user_id = user_id
        request.auth_user_name = name
        request.auth_actor_user_id = "actor-admin" if proxy else user_id
        request.auth_actor_name = "实际操作人" if proxy else name
        request.auth_is_proxy = proxy
        request.auth_can_use_system_admin = admin
        is_provider = ServiceProvider.objects.filter(auth_user_id=user_id).exists()
        is_provider_route = path.startswith("/api/after-sales/mobile") or path in {
            "/api/after-sales/providers/me",
            "/api/after-sales/providers/apply",
        }
        request.auth_token_claims = (
            {"chn": "wechat-mini", "aud": "after-sales-mobile"}
            if not admin and (is_provider or is_provider_route)
            else {"chn": "dingtalk", "aud": "platform"}
        )
        return request

    @staticmethod
    def data(response) -> dict:
        return json.loads(response.content.decode("utf-8"))


class CleanDomainMixin:
    def clear_domain(self):
        PrivateAttachment.objects.all().delete()
        TicketMessage.objects.all().delete()
        Reward.objects.all().delete()
        ServiceRating.objects.all().delete()
        FieldFeedback.objects.all().delete()
        ServiceTicket.objects.all().delete()
        SettlementEvent.objects.all().delete()
        Settlement.objects.all().delete()
        ServiceResource.objects.all().delete()
        ProjectAssignment.objects.all().delete()
        ProjectEvent.objects.all().delete()
        ProjectNode.objects.all().delete()
        ServiceProject.objects.all().delete()
        WorkflowCase.objects.all().delete()
        ServiceProvider.objects.all().delete()
        AppPermissionRule.objects.all().delete()


class AppPlatformTests(TestCase):
    def test_health_endpoints_are_public_and_readiness_checks_database(self):
        for path in (
            "/api/health/",
            "/api/health/live",
            "/api/health/ready",
            "/api/after-sales/health/",
            "/api/after-sales/health/live",
            "/api/after-sales/health/ready",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["ok"])

        with patch("after_sales_api.views.connection.cursor", side_effect=RuntimeError("down")):
            response = self.client.get("/api/after-sales/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "DATABASE_UNAVAILABLE")

    def test_business_api_requires_auth_and_public_path_matching_is_exact(self):
        for path in ("/api/after-sales/projects", "/api/after-sales/capabilities"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["code"], "MISSING_AUTH_TOKEN")
        response = self.client.get("/api/after-sales/health/ready/extra")
        self.assertEqual(response.status_code, 401)
        response = self.client.get("/api/after-sales/public/demo/extra")
        self.assertEqual(response.status_code, 401)

    def test_public_demo_only_exposes_one_enabled_standalone_public_resource(self):
        ServiceResource.objects.all().delete()
        ServiceResource.objects.create(
            title="内部项目资料",
            resource_type=ServiceResource.TYPE_MANUAL,
            audience=ServiceResource.AUDIENCE_ASSIGNED,
            summary="不得公开",
        )
        ServiceResource.objects.create(
            title="已停用公开资料",
            resource_type=ServiceResource.TYPE_VIDEO,
            audience=ServiceResource.AUDIENCE_PUBLIC,
            enabled=False,
        )
        expected = ServiceResource.objects.create(
            title="公开安装示范",
            resource_type=ServiceResource.TYPE_VIDEO,
            audience=ServiceResource.AUDIENCE_PUBLIC,
            summary="只展示标准安装示范",
            content="正式项目要求以登录后的项目资料为准。",
            tags=["公开示范"],
        )

        response = self.client.get("/api/after-sales/public/demo")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["item"], {
            "id": expected.id,
            "title": "公开安装示范",
            "resourceType": "video",
            "resourceTypeLabel": "安装视频",
            "summary": "只展示标准安装示范",
            "content": "正式项目要求以登录后的项目资料为准。",
            "externalUrl": "",
            "tags": ["公开示范"],
        })

    def test_cross_origin_write_is_blocked(self):
        middleware = SameOriginWriteMiddleware(lambda _request: JsonResponse({"ok": True}))
        request = RequestFactory().post(
            "/api/after-sales/projects",
            HTTP_HOST="platform.example.test",
            HTTP_ORIGIN="https://other.example.test",
            HTTP_SEC_FETCH_SITE="cross-site",
        )
        response = middleware(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["code"], "CROSS_ORIGIN_WRITE_BLOCKED")

    @override_settings(
        CSRF_TRUSTED_ORIGINS=["https://oa.hzmaijie.com", "https://oa.hzmaijie.com:4433"],
    )
    def test_dingtalk_trusted_origin_write_is_allowed_with_same_site_metadata(self):
        middleware = SameOriginWriteMiddleware(lambda _request: JsonResponse({"ok": True}))
        request = RequestFactory().patch(
            "/api/after-sales/providers/6",
            HTTP_HOST="oa.hzmaijie.com:4433",
            HTTP_ORIGIN="https://oa.hzmaijie.com",
            HTTP_SEC_FETCH_SITE="same-site",
        )

        self.assertEqual(middleware(request).status_code, 200)


class ProjectWorkflowTests(CleanDomainMixin, RequestMixin, TestCase):
    PRESALES_SUCCESS_OUTCOMES = {
        "early-approval": "approved",
        "late-approval": "approved",
        "early-plan-result": "passed",
        "construction-result": "won",
    }
    FIELD_NODE_KEYS = {
        "construction-work",
        "furniture-install",
        "device-install",
        "device-debug",
        "school-support",
        "project-acceptance",
    }

    def setUp(self):
        self.factory = RequestFactory()
        self.clear_domain()
        self.provider = ServiceProvider.objects.create(
            auth_user_id="provider-a",
            name="张师傅",
            role=ServiceProvider.ROLE_INSTALLER,
            certification_status=ServiceProvider.CERT_CERTIFIED,
            city="杭州",
            regions=["杭州"],
            skills=["设备安装"],
        )

    def test_project_detail_preserves_full_history_across_nodes(self):
        for service_type in ("presales", "midsales", "aftersales"):
            with self.subTest(service_type=service_type):
                project = self.create_project(service_type)
                first_node, second_node = list(project.nodes.all()[:2])
                oldest = ProjectEvent.objects.create(
                    project=project, node=first_node, event_type="node_version",
                    title="最早的节点版本", before_values={"estimatedFee": "10.00"},
                    after_values={"estimatedFee": "20.00"},
                    auth_user_id="manager-1", auth_user_name="项目经理",
                    actor_user_id="system-admin", actor_name="系统管理员",
                )
                ProjectEvent.objects.bulk_create([
                    ProjectEvent(
                        project=project, node=second_node if index % 2 else None,
                        event_type="node_update", title=f"历史记录 {index}",
                    )
                    for index in range(105)
                ])
                response = views.project_item(self.request(
                    "get", f"/api/after-sales/projects/{project.pk}",
                ), project.pk)
                self.assertEqual(response.status_code, 200)
                events = self.data(response)["item"]["events"]
                self.assertEqual(
                    [row["id"] for row in events],
                    list(project.events.values_list("id", flat=True)),
                )
                version = next(row for row in events if row["id"] == oldest.pk)
                self.assertEqual(version["nodeId"], first_node.pk)
                self.assertEqual(version["beforeValues"], {"estimatedFee": "10.00"})
                self.assertEqual(version["afterValues"], {"estimatedFee": "20.00"})
                self.assertEqual(version["authUserName"], "项目经理")
                self.assertEqual(version["actorName"], "系统管理员")
                self.assertTrue(any(row["nodeId"] == second_node.pk for row in events))
                self.assertTrue(any(row["nodeId"] is None for row in events))

    def create_project(self, service_type="midsales", disabled=None, name="浙江工业大学智慧教室项目"):
        payload = {
            "serviceType": service_type,
            "name": name,
            "customer": "浙江工业大学",
            "ownerUserId": "manager-1",
            "ownerName": "项目经理-陈明",
            "address": "杭州项目现场",
            "disabledNodeKeys": disabled or [],
        }
        if service_type == "aftersales":
            payload["businessData"] = AFTERSALES_DISPATCH_DATA
        response = views.projects_collection(self.request(
            "post",
            "/api/after-sales/projects",
            payload,
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        project = ServiceProject.objects.get(pk=self.data(response)["item"]["id"])
        if service_type == "presales":
            required_keys = {
                "early-plan", "budget-match", "project-filing",
                "late-plan", "device-plan", "budget", "device-budget",
                "cost-control", "device-cost-control", "rendering",
                "tender-plan", "layout", "bid-prep",
            }
            planned_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            for node in project.nodes.filter(node_key__in=required_keys, enabled=True):
                node.planned_start_at = planned_start
                node.planned_end_at = planned_start + timedelta(days=3)
                node.business_data = {
                    **(node.business_data or {}),
                    "managementAssignment": {
                        "userId": "manager-1",
                        "name": "项目经理-陈明",
                        "plannedStartDate": planned_start.date().isoformat(),
                        "plannedEndDate": (planned_start + timedelta(days=3)).date().isoformat(),
                        "note": "",
                    },
                }
                node.save(update_fields=["planned_start_at", "planned_end_at", "business_data"])
        return project

    def confirm_field_completion(self, project, node_key):
        node = project.nodes.get(node_key=node_key)
        now = timezone.now()
        assignment, _created = ProjectAssignment.objects.update_or_create(
            project=project,
            node=node,
            provider=self.provider,
            defaults={"status": ProjectAssignment.STATUS_COMPLETED, "completed_at": now},
        )
        node.business_data = {
            **(node.business_data or {}),
            "actualStartTime": now.isoformat(),
            "actualEndTime": now.isoformat(),
            "actualDuration": "0天0小时0分钟",
            "fieldSubmissions": {
                **((node.business_data or {}).get("fieldSubmissions") or {}),
                str(assignment.id): {
                    "submitted": True,
                    "submittedAt": now.isoformat(),
                    "providerId": self.provider.id,
                    "providerName": self.provider.name,
                },
            },
        }
        node.actual_start_at = now
        node.actual_end_at = now
        node.save(update_fields=["actual_start_at", "actual_end_at", "business_data"])
        return assignment

    def start_midsales_node(self, project, node_key):
        node = project.nodes.get(node_key=node_key)
        if node_key in self.FIELD_NODE_KEYS and not ProjectAssignment.objects.filter(
            project=project,
            node=node,
        ).exclude(status=ProjectAssignment.STATUS_CANCELLED).exists():
            ProjectAssignment.objects.create(
                project=project,
                node=node,
                provider=self.provider,
                status=ProjectAssignment.STATUS_ASSIGNED,
                standard_duration="3 天",
            )
        response = views.project_start(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/start",
            {"nodeKey": node_key},
        ), project.id)
        self.assertEqual(response.status_code, 200, self.data(response))
        project.refresh_from_db()
        return response

    def advance_presales_node(self, project, node_key, *, outcome=""):
        payload = {"nodeKey": node_key, "note": f"完成 {node_key}"}
        if outcome:
            payload["outcome"] = outcome
        response = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            payload,
        ), project.id)
        self.assertEqual(response.status_code, 200, self.data(response))
        project.refresh_from_db()
        return response

    def progress_presales_to(self, project, target_key):
        for _step in range(20):
            active_keys = list(project.nodes.filter(
                status=ProjectNode.STATUS_ACTIVE,
            ).order_by("sequence").values_list("node_key", flat=True))
            if target_key in active_keys:
                return
            self.assertTrue(active_keys, f"到达 {target_key} 前流程无可执行节点")
            for node_key in active_keys:
                self.advance_presales_node(
                    project,
                    node_key,
                    outcome=self.PRESALES_SUCCESS_OUTCOMES.get(node_key, ""),
                )
        self.fail(f"售前流程未能到达 {target_key}")

    def test_templates_are_created_for_all_business_types(self):
        expected = {"presales": 19, "midsales": 8, "aftersales": 3}
        for service_type, count in expected.items():
            with self.subTest(service_type=service_type):
                project = self.create_project(service_type, name=f"{service_type} 项目")
                self.assertEqual(project.nodes.count(), count)
                expected_active = 0 if service_type == "aftersales" else 1
                self.assertEqual(project.nodes.filter(status=ProjectNode.STATUS_ACTIVE).count(), expected_active)
                self.assertEqual(project.current_node_key, project.nodes.order_by("sequence").first().node_key)
                if service_type == "aftersales":
                    self.assertEqual(project.nodes.filter(enabled=True).count(), 1)

    # This assertion checks an immediate sync result on every database backend.
    @patch("after_sales_api.crm_source._in_memory_database", return_value=True)
    def test_project_list_planned_end_comes_from_current_node(self, _inline_sync):
        expected_date = (timezone.now() + timedelta(days=6)).date().isoformat()
        for service_type in ("presales", "midsales", "aftersales"):
            with self.subTest(service_type=service_type):
                project = self.create_project(service_type, name=f"{service_type} 列表日期")
                node = project.nodes.get(node_key=project.current_node_key)
                node.planned_end_at = timezone.now() + timedelta(days=6)
                node.save(update_fields=["planned_end_at"])
                crm_rows = []
                if service_type == "presales":
                    project.source_crm_id = "crm-planned-date-test"
                    project.save(update_fields=["source_crm_id"])
                    crm_rows = [{"id": project.source_crm_id, "name": project.name, "customerName": project.customer}]
                with patch("after_sales_api.crm_source._request_payload", return_value={"items": crm_rows}):
                    response = views.projects_collection(self.request(
                        "get",
                        "/api/after-sales/projects",
                        query={"type": service_type},
                    ))
                self.assertEqual(response.status_code, 200, self.data(response))
                item = next(row for row in self.data(response)["items"] if row["id"] == project.id)
                self.assertEqual(item["plannedEndDate"], "" if service_type == "presales" else expected_date)

    def test_project_creator_is_always_bound_as_owner(self):
        response = views.projects_collection(self.request(
            "post",
            "/api/after-sales/projects",
            {
                "serviceType": "presales",
                "name": "创建人绑定测试",
                "customer": "测试客户",
                "ownerUserId": "forged-user",
                "ownerName": "伪造负责人",
                "businessData": {
                    "projectInfo": {"owner": "伪造申请人", "reason": "测试"},
                    "projectInfoRecords": {"early-approval": {"owner": "伪造申请人"}},
                },
            },
            user_id="creator-user",
            name="当前创建人",
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        project = ServiceProject.objects.get(pk=self.data(response)["item"]["id"])
        self.assertEqual(project.owner_user_id, "creator-user")
        self.assertEqual(project.owner_name, "当前创建人")
        self.assertEqual(project.business_data["projectInfo"]["owner"], "当前创建人")
        self.assertEqual(
            project.business_data["projectInfoRecords"]["early-approval"]["owner"],
            "当前创建人",
        )

    def test_aftersales_create_serializes_dispatch_details_for_clients(self):
        response = views.projects_collection(self.request(
            "post",
            "/api/after-sales/projects",
            {
                "serviceType": "aftersales",
                "name": "售后订单资料展示",
                "customer": "测试客户",
                "ownerName": "售后项目经理",
                "address": "杭州现场地址",
                "summary": "现场任务说明",
                "businessData": AFTERSALES_DISPATCH_DATA,
            },
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        item = self.data(response)["item"]
        self.assertEqual(item["ownerName"], "系统管理员")
        self.assertFalse(ProjectAssignment.objects.filter(project_id=item["id"]).exists())
        self.assertEqual(item["address"], "杭州现场地址")
        self.assertEqual(item["summary"], "现场任务说明")
        self.assertEqual(item["businessData"]["managerContact"], "13800000000")
        self.assertEqual(item["businessData"]["feeAgreement"], "客户承担")
        self.assertEqual(item["businessData"]["feeRemark"], "按实际服务结算")
        self.assertEqual(item["businessData"]["products"][0]["name"], "迈杰智能讲台")

    def test_aftersales_planned_end_uses_assigned_duration(self):
        project = self.create_project("aftersales", name="售后计划时间计算")
        node = project.nodes.get(node_key="onsite-service")
        assigned = views.project_assignments(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/assignments",
            {
                "nodeKey": node.node_key,
                "providerId": self.provider.id,
                "standardDuration": "2 小时",
            },
        ), project.id)
        self.assertEqual(assigned.status_code, 201, self.data(assigned))

        saved = views.project_node_autosave(self.request(
            "patch",
            f"/api/after-sales/projects/{project.id}/nodes/{node.node_key}",
            {
                "plannedStartAt": "2026-09-09T10:00:00+08:00",
                "plannedEndAt": "2026-09-20T10:00:00+08:00",
            },
        ), project.id, node.node_key)
        self.assertEqual(saved.status_code, 200, self.data(saved))
        node.refresh_from_db()
        self.assertEqual(node.planned_start_at.isoformat(), "2026-09-09T02:00:00+00:00")
        self.assertEqual(node.planned_end_at.isoformat(), "2026-09-09T04:00:00+00:00")

        started = views.project_start(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/start",
            {"nodeKey": node.node_key},
        ), project.id)
        self.assertEqual(started.status_code, 200, self.data(started))
        node.refresh_from_db()
        self.assertEqual(node.planned_end_at.isoformat(), "2026-09-09T04:00:00+00:00")

    def test_midsales_start_preserves_manually_scheduled_end(self):
        project = self.create_project(name="售中手动排期")
        advanced = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": project.current_node_key, "note": "项目立项完成"},
        ), project.id)
        self.assertEqual(advanced.status_code, 200, self.data(advanced))
        project.refresh_from_db()
        node = project.nodes.get(node_key="construction-work")

        scheduled = views.project_node_autosave(self.request(
            "patch",
            f"/api/after-sales/projects/{project.id}/nodes/{node.node_key}",
            {
                "plannedStartAt": "2026-09-09T00:00:00+08:00",
                "plannedEndAt": "2026-09-20T23:59:00+08:00",
            },
        ), project.id, node.node_key)
        self.assertEqual(scheduled.status_code, 200, self.data(scheduled))
        assigned = views.project_assignments(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/assignments",
            {
                "nodeKey": node.node_key,
                "providerId": self.provider.id,
                "standardDuration": "3 天",
            },
        ), project.id)
        self.assertEqual(assigned.status_code, 201, self.data(assigned))

        started = views.project_start(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/start",
            {"nodeKey": node.node_key},
        ), project.id)
        self.assertEqual(started.status_code, 200, self.data(started))
        node.refresh_from_db()
        self.assertEqual(node.planned_start_at.isoformat(), "2026-09-08T16:00:00+00:00")
        self.assertEqual(node.planned_end_at.isoformat(), "2026-09-20T15:59:00+00:00")

    def test_midsales_start_does_not_derive_end_from_legacy_standard_duration(self):
        project = self.create_project(name="售中不使用标准工期")
        advanced = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": project.current_node_key, "note": "项目立项完成"},
        ), project.id)
        self.assertEqual(advanced.status_code, 200, self.data(advanced))
        project.refresh_from_db()
        node = project.nodes.get(node_key="construction-work")
        assigned = views.project_assignments(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/assignments",
            {
                "nodeKey": node.node_key,
                "providerId": self.provider.id,
                "standardDuration": "3 天",
            },
        ), project.id)
        self.assertEqual(assigned.status_code, 201, self.data(assigned))

        started = views.project_start(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/start",
            {"nodeKey": node.node_key},
        ), project.id)
        self.assertEqual(started.status_code, 200, self.data(started))
        node.refresh_from_db()
        self.assertIsNone(node.planned_end_at)

    def test_advance_enforces_order_and_skips_disabled_nodes(self):
        project = self.create_project(disabled=["furniture-install"])
        first = project.current_node_key
        response = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "not-current", "note": "错误版本"},
        ), project.id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.data(response)["code"], "PROJECT_NODE_STATE_INVALID")

        response = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": first, "note": "项目立项完成"},
        ), project.id)
        self.assertEqual(response.status_code, 200, self.data(response))
        project.refresh_from_db()
        self.assertEqual(project.current_node_key, "construction-work")

        self.start_midsales_node(project, "construction-work")
        self.confirm_field_completion(project, "construction-work")
        response = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "construction-work", "note": "施工完成"},
        ), project.id)
        self.assertEqual(response.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.current_node_key, "device-install")
        skipped = project.nodes.get(node_key="furniture-install")
        self.assertFalse(skipped.enabled)
        self.assertEqual(skipped.status, ProjectNode.STATUS_SKIPPED)
        event = ProjectEvent.objects.filter(project=project, event_type="node_completed").first()
        self.assertEqual(event.auth_user_id, "system-admin")
        self.assertEqual(event.actor_user_id, "system-admin")

    def test_advance_validates_and_persists_delivery_values(self):
        project = self.create_project()
        node_key = project.current_node_key

        invalid_quote = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": node_key, "businessData": {"externalQuote": "not-an-amount"}},
        ), project.id)
        self.assertEqual(invalid_quote.status_code, 400)
        self.assertEqual(self.data(invalid_quote)["code"], "INVALID_NUMBER")

        invalid_range = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {
                "nodeKey": node_key,
                "plannedStartAt": "2026-08-02T09:00:00+08:00",
                "plannedEndAt": "2026-08-01T18:00:00+08:00",
            },
        ), project.id)
        self.assertEqual(invalid_range.status_code, 400)
        self.assertEqual(self.data(invalid_range)["code"], "INVALID_PLANNED_TIME_RANGE")

        node = project.nodes.get(node_key=node_key)
        node.actual_fee = Decimal("880.50")
        node.save(update_fields=["actual_fee"])
        response = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {
                "nodeKey": node_key,
                "plannedStartAt": "2026-08-01T09:00:00+08:00",
                "plannedEndAt": "2026-08-02T18:00:00+08:00",
                "actualStartAt": "2026-08-01T09:30:00+08:00",
                "actualEndAt": "2026-08-02T17:00:00+08:00",
                "estimatedFee": "1000",
                "actualFee": "999.99",
                "businessData": {"externalQuote": "1200.00"},
            },
        ), project.id)
        self.assertEqual(response.status_code, 200, self.data(response))
        node = ProjectNode.objects.get(project=project, node_key=node_key)
        self.assertEqual(node.estimated_fee, Decimal("1000.00"))
        self.assertEqual(node.actual_fee, Decimal("880.50"))
        self.assertEqual(node.business_data["externalQuote"], "1200.00")

    def test_charge_node_advance_keeps_settlement_reminder_without_blocking(self):
        project = self.create_project()

        first = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": project.current_node_key, "note": "项目立项完成"},
        ), project.id)
        self.assertEqual(first.status_code, 200, self.data(first))
        project.refresh_from_db()
        self.assertEqual(project.current_node_key, "construction-work")
        construction = project.nodes.get(node_key="construction-work")
        self.start_midsales_node(project, "construction-work")
        construction.actual_fee = Decimal("880.50")
        construction.save(update_fields=["actual_fee"])
        self.confirm_field_completion(project, "construction-work")

        blocked_current = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {
                "nodeKey": "construction-work",
                "note": "工程施工完成",
            },
        ), project.id)
        self.assertEqual(blocked_current.status_code, 200, self.data(blocked_current))
        self.assertTrue(self.data(blocked_current)["item"]["settlementRequired"])
        project.refresh_from_db()
        self.assertEqual(project.current_node_key, "furniture-install")

        sources = views.settlement_sources(self.request("get", "/api/after-sales/settlement-sources", query={"projectId": project.id, "state": "available"}))
        self.assertEqual(sources.status_code, 200, self.data(sources))
        self.assertEqual(self.data(sources)["items"][0]["nodeKey"], "construction-work")

        created = views.settlements_collection(self.request(
            "post",
            "/api/after-sales/settlements",
            {
                "sourceNodeId": project.nodes.get(node_key="construction-work").id,
                "bearer": Settlement.BEARER_COMPANY,
            },
        ))
        self.assertEqual(created.status_code, 201, self.data(created))
        settlement_id = self.data(created)["item"]["id"]
        pending = views.settlement_item(self.request(
            "patch",
            f"/api/after-sales/settlements/{settlement_id}",
            {"status": Settlement.STATUS_PENDING, "expectedRevision": 1},
        ), settlement_id)
        self.assertEqual(pending.status_code, 200, self.data(pending))
        settled = views.settlement_item(self.request(
            "patch",
            f"/api/after-sales/settlements/{settlement_id}",
            {"status": Settlement.STATUS_SETTLED, "expectedRevision": 2},
        ), settlement_id)
        self.assertEqual(settled.status_code, 200, self.data(settled))

        self.start_midsales_node(project, "furniture-install")
        self.confirm_field_completion(project, "furniture-install")
        resumed = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "furniture-install", "note": "结算完成后继续推进"},
        ), project.id)
        self.assertEqual(resumed.status_code, 200, self.data(resumed))
        self.assertFalse(self.data(resumed)["item"]["settlementRequired"])

    def test_draft_settlement_can_be_confirmed_directly(self):
        project = self.create_project()
        first = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": project.current_node_key, "note": "项目立项完成"},
        ), project.id)
        self.assertEqual(first.status_code, 200, self.data(first))
        self.start_midsales_node(project, "construction-work")
        node = project.nodes.get(node_key="construction-work")
        node.actual_fee = Decimal("88.00")
        node.save(update_fields=["actual_fee"])
        self.confirm_field_completion(project, "construction-work")

        created = views.settlements_collection(self.request(
            "post",
            "/api/after-sales/settlements",
            {"sourceNodeId": node.id, "bearer": Settlement.BEARER_COMPANY},
        ))
        self.assertEqual(created.status_code, 201, self.data(created))
        settlement_id = self.data(created)["item"]["id"]
        settled = views.settlement_item(self.request(
            "patch",
            f"/api/after-sales/settlements/{settlement_id}",
            {"status": Settlement.STATUS_SETTLED, "expectedRevision": 1},
        ), settlement_id)
        self.assertEqual(settled.status_code, 200, self.data(settled))
        self.assertEqual(self.data(settled)["item"]["status"], Settlement.STATUS_SETTLED)

    def test_presales_charge_node_advances_before_settlement(self):
        project = self.create_project("presales", name="售前当前节点结算")
        self.advance_presales_node(project, "early-approval", outcome="approved")
        project.refresh_from_db()
        self.assertEqual(project.current_node_key, "early-plan")
        node = project.nodes.get(node_key="early-plan")
        node.actual_fee = Decimal("260.00")
        node.save(update_fields=["actual_fee"])

        blocked = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": node.node_key, "note": "方案完成"},
        ), project.id)
        self.assertEqual(blocked.status_code, 200, self.data(blocked))
        self.assertTrue(self.data(blocked)["item"]["settlementRequired"])

        sources = views.settlement_sources(self.request(
            "get",
            "/api/after-sales/settlement-sources",
            query={"projectId": project.id, "state": "available"},
        ))
        self.assertEqual(sources.status_code, 200, self.data(sources))
        self.assertIn(node.id, {item["sourceNodeId"] for item in self.data(sources)["items"]})

    def test_assignment_controls_provider_visibility_and_operation(self):
        project = self.create_project()
        response = views.project_assignments(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/assignments",
            {
                "nodeKey": "construction-work",
                "providerId": self.provider.id,
                "role": "现场负责人",
                "plannedStartDate": "2026-08-01",
                "standardDuration": "5 天",
            },
        ), project.id)
        self.assertEqual(response.status_code, 201, self.data(response))
        self.assertEqual(ProjectAssignment.objects.count(), 1)
        self.assertEqual(self.data(response)["item"]["plannedStartDate"], "2026-08-01")
        self.assertEqual(self.data(response)["item"]["standardDuration"], "5 天")

        list_response = views.projects_collection(self.request(
            "get",
            "/api/after-sales/projects",
            user_id="provider-a",
            name="张师傅",
            admin=False,
        ))
        self.assertEqual(list_response.status_code, 403)
        self.assertEqual(self.data(list_response)["code"], "APP_ADMIN_REQUIRED")

        mobile_response = views.mobile_home(self.request(
            "get",
            "/api/after-sales/mobile/home",
            user_id="provider-a",
            name="张师傅",
            admin=False,
        ))
        self.assertEqual(mobile_response.status_code, 200)
        self.assertEqual(len(self.data(mobile_response)["tasks"]), 1)

        advance_response = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": project.current_node_key, "note": "现场任务完成"},
            user_id="provider-a",
            name="张师傅",
            admin=False,
        ), project.id)
        self.assertEqual(advance_response.status_code, 403, self.data(advance_response))
        assignment = ProjectAssignment.objects.get()
        self.assertEqual(assignment.status, ProjectAssignment.STATUS_ASSIGNED)

    def test_presales_personnel_requires_assignment_without_node_schedule(self):
        project = self.create_project("presales", name="售前管理端人员排期")
        nodes = list(project.nodes.order_by("sequence"))
        self.assertEqual(services._presales_approval_personnel_errors(project, "early-approval", nodes), [])

        target = project.nodes.get(node_key="early-plan")
        target.planned_end_at = None
        target.save(update_fields=["planned_end_at"])
        errors = services._presales_approval_personnel_errors(
            project,
            "early-approval",
            list(project.nodes.order_by("sequence")),
        )
        self.assertEqual(errors, [])

        saved = views.project_node_autosave(self.request(
            "patch",
            f"/api/after-sales/projects/{project.id}/nodes/early-plan",
            {
                "plannedStartAt": "2026-09-14T00:00:00+08:00",
                "plannedEndAt": "2026-09-18T23:59:00+08:00",
                "businessData": {
                    "managementAssignment": {
                        "userId": "dingtalk-user-1",
                        "name": "钉钉项目人员",
                        "plannedStartDate": "2026-09-14",
                        "plannedEndDate": "2026-09-18",
                        "note": "负责前期方案",
                    },
                },
            },
        ), project.id, "early-plan")
        self.assertEqual(saved.status_code, 200, self.data(saved))
        target.refresh_from_db()
        self.assertEqual(target.business_data["managementAssignment"]["userId"], "dingtalk-user-1")
        self.assertIsNone(target.planned_end_at)

        forbidden = views.project_assignments(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/assignments",
            {
                "nodeKey": "early-plan",
                "providerId": self.provider.id,
            },
        ), project.id)
        self.assertEqual(forbidden.status_code, 409, self.data(forbidden))
        self.assertEqual(self.data(forbidden)["code"], "PRESALES_PROVIDER_ASSIGNMENT_FORBIDDEN")

    def test_provider_metrics_follow_completed_assignments_and_service_ratings(self):
        project = self.create_project()
        node = project.nodes.get(node_key="construction-work")
        current_month_assignment = ProjectAssignment.objects.create(
            project=project,
            node=node,
            provider=self.provider,
            status=ProjectAssignment.STATUS_COMPLETED,
            completed_at=timezone.now(),
        )
        previous_month_assignment = ProjectAssignment.objects.create(
            project=project,
            node=project.nodes.get(node_key="device-install"),
            provider=self.provider,
            status=ProjectAssignment.STATUS_COMPLETED,
            completed_at=timezone.now() - timedelta(days=45),
        )
        self.assertNotEqual(current_month_assignment.id, previous_month_assignment.id)
        rated = views.ratings_collection(self.request(
            "post",
            "/api/after-sales/ratings",
            {
                "projectId": project.id,
                "nodeKey": node.node_key,
                "providerId": self.provider.id,
                "rating": 4,
            },
        ))
        self.assertEqual(rated.status_code, 201, self.data(rated))
        self.assertEqual(ServiceRating.objects.count(), 1)
        self.assertEqual(FieldFeedback.objects.count(), 0)

        response = views.providers_collection(self.request(
            "get",
            "/api/after-sales/providers",
        ))
        self.assertEqual(response.status_code, 200, self.data(response))
        item = next(row for row in self.data(response)["items"] if row["id"] == self.provider.id)
        self.assertEqual(item["monthOrders"], 1)
        self.assertEqual(item["totalOrders"], 2)
        self.assertEqual(item["score"], "4.00")
        self.assertEqual(item["scoreRatingCount"], 1)
        detail = views.provider_item(self.request(
            "get",
            f"/api/after-sales/providers/{self.provider.id}",
        ), self.provider.id)
        self.assertEqual(detail.status_code, 200, self.data(detail))
        self.assertEqual(self.data(detail)["item"]["scoreSummary"]["count"], 1)
        self.assertEqual(self.data(detail)["item"]["scoreSummary"]["source"], "rating")

    def test_service_rating_requires_completed_assignment_and_updates_existing_rating(self):
        project = self.create_project()
        node = project.nodes.get(node_key="construction-work")
        assignment = ProjectAssignment.objects.create(
            project=project,
            node=node,
            provider=self.provider,
            status=ProjectAssignment.STATUS_IN_PROGRESS,
        )
        payload = {
            "projectId": project.id,
            "nodeKey": node.node_key,
            "providerId": self.provider.id,
            "rating": 3,
        }
        blocked = views.ratings_collection(self.request("post", "/api/after-sales/ratings", payload))
        self.assertEqual(blocked.status_code, 409, self.data(blocked))
        self.assertEqual(self.data(blocked)["code"], "SERVICE_RATING_COMPLETION_REQUIRED")

        assignment.status = ProjectAssignment.STATUS_COMPLETED
        assignment.completed_at = timezone.now()
        assignment.save(update_fields=["status", "completed_at"])
        created = views.ratings_collection(self.request("post", "/api/after-sales/ratings", payload))
        self.assertEqual(created.status_code, 201, self.data(created))
        payload["rating"] = 5
        updated = views.ratings_collection(self.request("post", "/api/after-sales/ratings", payload))
        self.assertEqual(updated.status_code, 201, self.data(updated))
        self.assertEqual(ServiceRating.objects.count(), 1)
        self.assertEqual(ServiceRating.objects.get().rating, 5)

        presales_project = self.create_project("presales", name="售前不评分")
        presales_node = presales_project.nodes.get(node_key="early-plan")
        ProjectAssignment.objects.create(
            project=presales_project,
            node=presales_node,
            provider=self.provider,
            status=ProjectAssignment.STATUS_COMPLETED,
            completed_at=timezone.now(),
        )
        presales_payload = {
            "projectId": presales_project.id,
            "nodeKey": presales_node.node_key,
            "providerId": self.provider.id,
            "rating": 5,
        }
        presales_rating = views.ratings_collection(self.request("post", "/api/after-sales/ratings", presales_payload))
        self.assertEqual(presales_rating.status_code, 409, self.data(presales_rating))
        self.assertEqual(ServiceRating.objects.count(), 1)

    def test_midsales_personnel_matrix_has_six_nodes_and_replaces_current_provider(self):
        project = self.create_project()
        disallowed = views.project_assignments(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/assignments",
            {"nodeKey": "midsales-project", "providerId": self.provider.id},
        ), project.id)
        self.assertEqual(disallowed.status_code, 409)
        self.assertEqual(self.data(disallowed)["code"], "MIDSALES_NODE_NOT_ASSIGNABLE")

        without_date = views.project_assignments(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/assignments",
            {
                "nodeKey": "construction-work",
                "providerId": self.provider.id,
                "standardDuration": "3 天",
            },
        ), project.id)
        self.assertEqual(without_date.status_code, 201, self.data(without_date))
        self.assertEqual(self.data(without_date)["item"]["providerId"], self.provider.id)
        self.assertEqual(self.data(without_date)["item"]["plannedStartDate"], "")

        assignable_keys = [
            "construction-work",
            "furniture-install",
            "device-install",
            "device-debug",
            "school-support",
            "project-acceptance",
        ]
        for index, node_key in enumerate(assignable_keys, start=1):
            response = views.project_assignments(self.request(
                "post",
                f"/api/after-sales/projects/{project.id}/assignments",
                {
                    "nodeKey": node_key,
                    "providerId": self.provider.id,
                    "plannedStartDate": f"2026-08-{index:02d}",
                    "standardDuration": f"{index + 1} 天",
                },
            ), project.id)
            self.assertEqual(response.status_code, 201, self.data(response))
        self.assertEqual(
            ProjectAssignment.objects.exclude(status=ProjectAssignment.STATUS_CANCELLED).count(),
            6,
        )

        replacement = ServiceProvider.objects.create(
            auth_user_id="provider-b",
            name="李工",
            role=ServiceProvider.ROLE_SUPPORT,
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        replaced = views.project_assignments(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/assignments",
            {
                "nodeKey": "device-debug",
                "providerId": replacement.id,
                "plannedStartDate": "2026-08-20",
                "standardDuration": "4 天",
            },
        ), project.id)
        self.assertEqual(replaced.status_code, 201, self.data(replaced))
        old_assignment = ProjectAssignment.objects.get(node__node_key="device-debug", provider=self.provider)
        self.assertEqual(old_assignment.status, ProjectAssignment.STATUS_CANCELLED)
        self.assertEqual(self.data(replaced)["item"]["providerId"], replacement.id)
        self.assertEqual(self.data(replaced)["item"]["plannedStartDate"], "2026-08-20")
        self.assertEqual(self.data(replaced)["item"]["standardDuration"], "4 天")

        inherited_provider = ServiceProvider.objects.create(
            auth_user_id="provider-c",
            name="王工",
            role=ServiceProvider.ROLE_INSTALLER,
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        inherited = views.project_assignments(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/assignments",
            {"nodeKey": "device-debug", "providerId": inherited_provider.id},
        ), project.id)
        self.assertEqual(inherited.status_code, 201, self.data(inherited))
        self.assertEqual(self.data(inherited)["item"]["plannedStartDate"], "2026-08-20")
        self.assertEqual(self.data(inherited)["item"]["standardDuration"], "4 天")

    def test_projects_can_be_filtered_by_assigned_provider(self):
        linked = self.create_project(name="张师傅关联项目")
        other = self.create_project(name="其他人员项目")
        cancelled = self.create_project(name="已取消指派项目")
        replacement = ServiceProvider.objects.create(
            auth_user_id="provider-b",
            name="李工",
            role=ServiceProvider.ROLE_SUPPORT,
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        ProjectAssignment.objects.create(
            project=linked,
            node=linked.nodes.get(node_key="construction-work"),
            provider=self.provider,
        )
        ProjectAssignment.objects.create(
            project=linked,
            node=linked.nodes.get(node_key="device-install"),
            provider=replacement,
            status=ProjectAssignment.STATUS_CANCELLED,
        )
        ProjectAssignment.objects.create(
            project=other,
            node=other.nodes.get(node_key="construction-work"),
            provider=replacement,
        )
        ProjectAssignment.objects.create(
            project=cancelled,
            node=cancelled.nodes.get(node_key="construction-work"),
            provider=self.provider,
            status=ProjectAssignment.STATUS_CANCELLED,
        )

        response = views.projects_collection(self.request(
            "get",
            "/api/after-sales/projects",
            query={"providerId": self.provider.id, "pageSize": 100},
        ))

        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertEqual(
            [item["id"] for item in self.data(response)["items"]],
            [linked.id],
        )

    def test_admin_is_required_and_proxy_uses_effective_subject_permission(self):
        regular = views.projects_collection(self.request(
            "post",
            "/api/after-sales/projects",
            {"serviceType": "aftersales", "name": "无权项目", "customer": "客户"},
            user_id="provider-a",
            admin=False,
        ))
        self.assertEqual(regular.status_code, 403)
        self.assertEqual(self.data(regular)["code"], "APP_ADMIN_REQUIRED")

        proxied = views.providers_collection(self.request(
            "post",
            "/api/after-sales/providers",
            {"authUserId": "x", "name": "代理新增", "role": "installer"},
            user_id="provider-a",
            admin=False,
            proxy=True,
        ))
        self.assertEqual(proxied.status_code, 403)

        whitelisted_target = views.providers_collection(self.request(
            "post",
            "/api/after-sales/providers",
            {"authUserId": "x", "name": "白名单代理新增", "role": "installer"},
            user_id="whitelisted-proxy-target",
            admin=True,
            proxy=True,
        ))
        self.assertEqual(whitelisted_target.status_code, 405)
        self.assertEqual(self.data(whitelisted_target)["code"], "PROVIDER_SELF_REGISTRATION_REQUIRED")

    def test_ungranted_management_user_cannot_use_the_module(self):
        regular = views.projects_collection(self.request(
            "post",
            "/api/after-sales/projects",
            {
                "serviceType": "midsales",
                "name": "普通用户项目",
                "customer": "普通用户客户",
                "ownerUserId": "office-user",
                "ownerName": "业务用户",
                "address": "杭州项目现场",
            },
            user_id="office-user",
            name="业务用户",
            admin=False,
        ))
        self.assertEqual(regular.status_code, 403, self.data(regular))
        self.assertEqual(self.data(regular)["code"], "APP_ACCESS_DENIED")
        self.assertFalse(ServiceProject.objects.filter(name="普通用户项目").exists())

        settings = views.permissions_collection(self.request(
            "get",
            "/api/after-sales/permissions",
            user_id="office-user",
            name="业务用户",
            admin=False,
        ))
        self.assertEqual(settings.status_code, 403, self.data(settings))
        self.assertEqual(self.data(settings)["code"], "APP_ADMIN_REQUIRED")

        session = views.session(self.request(
            "get",
            "/api/after-sales/session/",
            user_id="office-user",
            name="业务用户",
            admin=False,
        ))
        self.assertEqual(session.status_code, 200, self.data(session))
        self.assertFalse(self.data(session)["canManageApp"])
        self.assertFalse(self.data(session)["canManageSettings"])
        self.assertFalse(self.data(session)["canCreateProjects"])

    def test_management_cannot_create_provider_from_dingtalk_directory(self):
        response = views.providers_collection(self.request(
            "post",
            "/api/after-sales/providers",
            {
                "authUserId": "auth-new-provider",
                "name": "钉钉人员",
            },
        ))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.data(response)["code"], "PROVIDER_SELF_REGISTRATION_REQUIRED")
        self.assertFalse(ServiceProvider.objects.filter(auth_user_id="auth-new-provider").exists())

    def test_search_type_status_and_pagination(self):
        self.create_project("presales", name="杭州智慧教室售前")
        self.create_project("midsales", name="宁波设备安装")
        self.create_project("aftersales", name="杭州智慧教室售后")
        response = views.projects_collection(self.request(
            "get",
            "/api/after-sales/projects",
            query={"search": "杭州", "type": "aftersales", "status": "in_progress", "page": 1, "pageSize": 1},
        ))
        data = self.data(response)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["pageSize"], 1)
        self.assertEqual(data["items"][0]["serviceType"], "aftersales")

    def test_presales_auto_start_tracks_unlock_time_without_overwriting_parallel_start(self):
        project = self.create_project("presales", name="售前自动开始")
        first = project.nodes.get(node_key="early-approval")
        self.assertIsNotNone(first.actual_start_at)
        self.assertFalse(project.nodes.exclude(pk=first.pk).exclude(actual_start_at=None).exists())
        unlocked_at = timezone.now() + timedelta(minutes=1)
        with patch.object(services.timezone, "now", return_value=unlocked_at):
            self.advance_presales_node(project, "early-approval", outcome="approved")
        for key in ("early-plan", "budget-match"):
            self.assertEqual(project.nodes.get(node_key=key).actual_start_at, unlocked_at)
        self.assertIsNone(project.nodes.get(node_key="project-filing").actual_start_at)
        manual_start = unlocked_at - timedelta(hours=1)
        response = views.project_node_autosave(self.request("patch", "/", {
            "actualStartAt": manual_start.isoformat(),
        }), project.pk, "early-plan")
        self.assertEqual(response.status_code, 200, self.data(response))
        filing_at = unlocked_at + timedelta(minutes=1)
        with patch.object(services.timezone, "now", return_value=filing_at):
            self.advance_presales_node(project, "budget-match")
        self.assertEqual(project.nodes.get(node_key="early-plan").actual_start_at, manual_start)
        self.assertEqual(project.nodes.get(node_key="project-filing").actual_start_at, filing_at)
        self.assertIsNone(project.nodes.get(node_key="early-plan-result").actual_start_at)
        # An older client calling start again cannot restart the clock or
        # change the current node after the server has already started it.
        current_key = project.current_node_key
        events = project.events.count()
        response = views.project_start(self.request("post", "/", {"nodeKey": "project-filing"}), project.pk)
        self.assertEqual(response.status_code, 200, self.data(response))
        project.refresh_from_db()
        self.assertEqual(project.current_node_key, current_key)
        self.assertEqual(project.events.count(), events)
        self.assertEqual(project.nodes.get(node_key="project-filing").actual_start_at, filing_at)

    def test_presales_reopen_automatically_starts_ready_nodes_and_rejects_locked_branch(self):
        project = self.create_project("presales", name="售前回退自动开始")
        self.advance_presales_node(project, "early-approval", outcome="approved")
        self.advance_presales_node(project, "early-plan")
        previous_start = project.nodes.get(node_key="early-plan").actual_start_at
        response = views.project_reopen(self.request("post", "/", {"nodeKey": "early-plan"}), project.pk)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertEqual(set(project.nodes.filter(status="active").values_list("node_key", flat=True)),
                         {"early-plan", "budget-match"})
        self.assertEqual(project.nodes.get(node_key="early-plan").actual_start_at, previous_start)
        self.assertIsNone(project.nodes.get(node_key="project-filing").actual_start_at)
        self.progress_presales_to(project, "late-approval")
        self.advance_presales_node(project, "late-approval", outcome="approved")
        for key in ("late-plan", "budget", "cost-control", "rendering"):
            self.advance_presales_node(project, key)
        response = views.project_reopen(self.request("post", "/", {"nodeKey": "device-budget"}), project.pk)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.data(response)["code"], "PRESALES_NODE_LOCKED")
        self.assertIsNone(project.nodes.get(node_key="device-budget").actual_start_at)
        other_start = project.nodes.get(node_key="device-plan").actual_start_at
        response = views.project_reopen(self.request("post", "/", {"nodeKey": "layout"}), project.pk)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertEqual(self.data(response)["item"]["currentNodeKey"], "rendering")
        self.assertEqual(project.nodes.get(node_key="rendering").status, "active")
        self.assertEqual(project.nodes.get(node_key="layout").status, "pending")
        self.assertEqual(project.nodes.get(node_key="device-plan").status, "active")
        self.assertEqual(project.nodes.get(node_key="device-plan").actual_start_at, other_start)

    def test_presales_reopen_clears_downstream_outcomes_and_preserves_completed_parallel_branch(self):
        project = self.create_project("presales", name="售前回退分支隔离")
        self.progress_presales_to(project, "construction")
        other = project.nodes.get(node_key="project-filing")
        other_history = (other.status, other.actual_start_at, other.actual_end_at, other.completed_at)
        response = views.project_reopen(self.request("post", "/", {"nodeKey": "early-plan"}), project.pk)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertEqual(set(project.nodes.filter(status="active").values_list("node_key", flat=True)), {"early-plan"})
        for key in ("early-plan-result", "late-approval", "construction-result"):
            node = project.nodes.get(node_key=key)
            self.assertEqual(node.status, "pending")
            self.assertNotIn("outcome", node.business_data)
        other.refresh_from_db()
        self.assertEqual((other.status, other.actual_start_at, other.actual_end_at, other.completed_at), other_history)

    def test_presales_early_branches_advance_independently_and_join_at_result(self):
        project = self.create_project("presales", name="售前分支流程")

        missing_outcome = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "early-approval", "note": "审批完成"},
        ), project.id)
        self.assertEqual(missing_outcome.status_code, 400)
        self.assertEqual(self.data(missing_outcome)["code"], "PRESALES_OUTCOME_REQUIRED")

        approved = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "early-approval", "outcome": "approved", "note": "同意立项"},
        ), project.id)
        self.assertEqual(approved.status_code, 200, self.data(approved))
        project.refresh_from_db()
        active_keys = set(project.nodes.filter(status=ProjectNode.STATUS_ACTIVE).values_list("node_key", flat=True))
        self.assertEqual(active_keys, {"early-plan", "budget-match"})
        self.assertEqual(project.nodes.get(node_key="project-filing").status, ProjectNode.STATUS_PENDING)
        self.assertEqual(project.nodes.get(node_key="early-plan-result").status, ProjectNode.STATUS_PENDING)
        self.assertEqual(project.nodes.get(node_key="late-approval").status, ProjectNode.STATUS_PENDING)

        too_early = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "early-plan-result", "outcome": "passed"},
        ), project.id)
        self.assertEqual(too_early.status_code, 409)
        self.assertEqual(self.data(too_early)["code"], "PROJECT_NODE_STATE_INVALID")

        self.advance_presales_node(project, "budget-match")
        active_keys = set(project.nodes.filter(status=ProjectNode.STATUS_ACTIVE).values_list("node_key", flat=True))
        self.assertEqual(active_keys, {"early-plan", "project-filing"})
        self.assertEqual(project.nodes.get(node_key="early-plan-result").status, ProjectNode.STATUS_PENDING)

        self.advance_presales_node(project, "project-filing")
        active_keys = set(project.nodes.filter(status=ProjectNode.STATUS_ACTIVE).values_list("node_key", flat=True))
        self.assertEqual(active_keys, {"early-plan"})
        self.assertEqual(project.nodes.get(node_key="early-plan-result").status, ProjectNode.STATUS_PENDING)

        self.advance_presales_node(project, "early-plan")
        active_keys = set(project.nodes.filter(status=ProjectNode.STATUS_ACTIVE).values_list("node_key", flat=True))
        self.assertEqual(active_keys, {"early-plan-result"})

        self.advance_presales_node(project, "early-plan-result", outcome="passed")
        self.assertEqual(project.nodes.get(node_key="late-approval").status, ProjectNode.STATUS_ACTIVE)
        self.assertEqual(project.nodes.get(node_key="construction").status, ProjectNode.STATUS_PENDING)

    def test_presales_delivery_nodes_advance_without_round_review_results(self):
        project = self.create_project("presales", name="售前推进无需逐轮审核")
        for _step in range(20):
            active_nodes = list(project.nodes.filter(
                status=ProjectNode.STATUS_ACTIVE,
            ).order_by("sequence"))
            if any(node.node_key == "project-end" for node in active_nodes):
                break
            self.assertTrue(active_nodes)
            for node in active_nodes:
                self.assertIsNotNone(node.actual_start_at, f"{node.node_key} must start as soon as it unlocks")
                if node.kind == "delivery":
                    rounds = [{"designDate": "2026-09-20", "result": "驳回", "note": "已完成本轮记录", "attachmentIds": []}]
                    saved = views.project_node_autosave(self.request(
                        "patch",
                        f"/api/after-sales/projects/{project.id}/nodes/{node.node_key}/autosave",
                        {"businessData": {"schemeRounds": rounds}},
                    ), project.id, node.node_key)
                    self.assertEqual(saved.status_code, 200, self.data(saved))
                    self.assertNotIn("result", project.nodes.get(pk=node.pk).business_data["schemeRounds"][0])
                    passed = views.project_advance(self.request(
                        "post",
                        f"/api/after-sales/projects/{project.id}/advance",
                        {"nodeKey": node.node_key, "businessData": {"schemeRounds": rounds}},
                    ), project.id)
                    self.assertEqual(passed.status_code, 200, self.data(passed))
                    completed = project.nodes.get(pk=node.pk)
                    self.assertEqual(completed.status, ProjectNode.STATUS_COMPLETED)
                    self.assertNotIn("result", completed.business_data["schemeRounds"][0])
                else:
                    self.advance_presales_node(
                        project, node.node_key,
                        outcome=self.PRESALES_SUCCESS_OUTCOMES.get(node.node_key, ""),
                    )
            project.refresh_from_db()
        else:
            self.fail("售前交付节点未能推进到结束标识")

    def test_presales_late_branches_advance_independently_and_join_at_result(self):
        project = self.create_project("presales", name="售前后期并行汇合")
        self.progress_presales_to(project, "late-approval")
        self.advance_presales_node(project, "late-approval", outcome="approved")

        upper_branch = ("late-plan", "budget", "cost-control", "rendering", "layout")
        for index, node_key in enumerate(upper_branch):
            with self.subTest(branch="upper", node=node_key):
                active_keys = set(project.nodes.filter(
                    status=ProjectNode.STATUS_ACTIVE,
                ).values_list("node_key", flat=True))
                self.assertIn(node_key, active_keys)
                self.assertIn("device-plan", active_keys)
                self.advance_presales_node(project, node_key)
                active_keys = set(project.nodes.filter(
                    status=ProjectNode.STATUS_ACTIVE,
                ).values_list("node_key", flat=True))
                expected_upper = {upper_branch[index + 1]} if index + 1 < len(upper_branch) else set()
                self.assertEqual(active_keys, expected_upper | {"device-plan"})
                self.assertEqual(
                    project.nodes.get(node_key="construction-result").status,
                    ProjectNode.STATUS_PENDING,
                )

        lower_branch = (
            "device-plan",
            "device-budget",
            "device-cost-control",
            "tender-plan",
            "bid-prep",
        )
        for index, node_key in enumerate(lower_branch):
            with self.subTest(branch="lower", node=node_key):
                active_keys = set(project.nodes.filter(
                    status=ProjectNode.STATUS_ACTIVE,
                ).values_list("node_key", flat=True))
                self.assertEqual(active_keys, {node_key})
                self.advance_presales_node(project, node_key)
                active_keys = set(project.nodes.filter(
                    status=ProjectNode.STATUS_ACTIVE,
                ).values_list("node_key", flat=True))
                expected = (
                    {lower_branch[index + 1]}
                    if index + 1 < len(lower_branch)
                    else {"construction-result"}
                )
                self.assertEqual(active_keys, expected)

    def test_presales_only_won_result_can_enter_construction_and_finish(self):
        project = self.create_project("presales", name="售前中标施工图")
        self.progress_presales_to(project, "construction-result")

        wrong_outcome = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "construction-result", "outcome": "passed"},
        ), project.id)
        self.assertEqual(wrong_outcome.status_code, 400, self.data(wrong_outcome))
        self.assertEqual(self.data(wrong_outcome)["code"], "PRESALES_OUTCOME_REQUIRED")

        self.advance_presales_node(project, "construction-result", outcome="won")
        self.assertEqual(project.nodes.get(node_key="construction").status, ProjectNode.STATUS_ACTIVE)
        self.assertEqual(project.nodes.get(node_key="project-end").status, ProjectNode.STATUS_PENDING)

        too_early = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "project-end"},
        ), project.id)
        self.assertEqual(too_early.status_code, 409, self.data(too_early))
        self.assertEqual(self.data(too_early)["code"], "PROJECT_NODE_STATE_INVALID")

        self.advance_presales_node(project, "construction")
        self.assertEqual(project.nodes.get(node_key="project-end").status, ProjectNode.STATUS_ACTIVE)
        project.nodes.filter(node_key="project-end").update(business_data={
            "midsalesNodeKeys": [row[0] for row in services.MIDSALES_NODE_TEMPLATE],
        })
        self.advance_presales_node(project, "project-end")
        self.assertEqual(project.status, ServiceProject.STATUS_COMPLETED)
        self.assertEqual(project.current_node_key, "")

    def test_presales_terminal_outcomes_restore_only_the_origin_node(self):
        scenarios = (
            ("early-approval", "denied", ServiceProject.STATUS_CANCELLED, "approved", {"early-plan", "budget-match"}),
            ("early-plan-result", "failed", ServiceProject.STATUS_CANCELLED, "passed", {"late-approval"}),
            ("early-plan-result", "abandoned", ServiceProject.STATUS_CANCELLED, "passed", {"late-approval"}),
            ("early-plan-result", "suspended", ServiceProject.STATUS_BLOCKED, "passed", {"late-approval"}),
            ("late-approval", "denied", ServiceProject.STATUS_CANCELLED, "approved", {"late-plan", "device-plan"}),
            ("construction-result", "failed", ServiceProject.STATUS_CANCELLED, "won", {"construction"}),
            ("construction-result", "abandoned", ServiceProject.STATUS_CANCELLED, "won", {"construction"}),
            ("construction-result", "suspended", ServiceProject.STATUS_BLOCKED, "won", {"construction"}),
        )
        for index, (node_key, terminal_outcome, terminal_status, success_outcome, next_keys) in enumerate(scenarios):
            with self.subTest(node=node_key, outcome=terminal_outcome):
                project = self.create_project(
                    "presales",
                    name=f"售前终止恢复-{node_key}-{terminal_outcome}",
                )
                self.progress_presales_to(project, node_key)
                self.advance_presales_node(project, node_key, outcome=terminal_outcome)

                self.assertEqual(project.status, terminal_status)
                self.assertEqual(project.current_node_key, node_key)
                self.assertEqual(project.business_data["terminalOutcome"], terminal_outcome)
                self.assertEqual(project.business_data["terminalNodeKey"], node_key)
                self.assertIsNotNone(project.actual_end_date)
                self.assertFalse(project.nodes.filter(status=ProjectNode.STATUS_ACTIVE).exists())

                if index == 0:
                    wrong_target = views.project_reopen(self.request(
                        "post",
                        f"/api/after-sales/projects/{project.id}/reopen",
                        {"nodeKey": "early-plan", "note": "错误恢复节点"},
                    ), project.id)
                    self.assertEqual(wrong_target.status_code, 409, self.data(wrong_target))
                    self.assertEqual(self.data(wrong_target)["code"], "PRESALES_RESTORE_TARGET_INVALID")

                restored = views.project_reopen(self.request(
                    "post",
                    f"/api/after-sales/projects/{project.id}/reopen",
                    {"nodeKey": node_key, "note": "条件已变更，恢复处理"},
                ), project.id)
                self.assertEqual(restored.status_code, 200, self.data(restored))
                project.refresh_from_db()
                restored_node = project.nodes.get(node_key=node_key)
                active_keys = set(project.nodes.filter(
                    status=ProjectNode.STATUS_ACTIVE,
                ).values_list("node_key", flat=True))
                self.assertEqual(project.status, ServiceProject.STATUS_IN_PROGRESS)
                self.assertEqual(active_keys, {node_key})
                self.assertEqual(restored_node.status, ProjectNode.STATUS_ACTIVE)
                self.assertNotIn("outcome", restored_node.business_data)
                self.assertNotIn("terminalOutcome", project.business_data)
                self.assertNotIn("terminalNodeKey", project.business_data)
                self.assertIsNone(project.actual_end_date)

                self.advance_presales_node(project, node_key, outcome=success_outcome)
                active_keys = set(project.nodes.filter(
                    status=ProjectNode.STATUS_ACTIVE,
                ).values_list("node_key", flat=True))
                self.assertEqual(active_keys, next_keys)

    def test_presales_delivery_node_cannot_inject_a_terminal_outcome(self):
        project = self.create_project("presales", name="售前交付节点结果校验")
        self.advance_presales_node(project, "early-approval", outcome="approved")

        response = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "early-plan", "outcome": "failed", "note": "伪造终止结果"},
        ), project.id)
        self.assertEqual(response.status_code, 400, self.data(response))
        self.assertEqual(self.data(response)["code"], "PRESALES_OUTCOME_NOT_ALLOWED")
        project.refresh_from_db()
        self.assertEqual(project.status, ServiceProject.STATUS_IN_PROGRESS)
        self.assertEqual(
            project.nodes.get(node_key="early-plan").status,
            ProjectNode.STATUS_ACTIVE,
        )

        empty_outcome = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "early-plan", "outcome": "", "note": "正常关闭交付节点"},
        ), project.id)
        self.assertEqual(empty_outcome.status_code, 200, self.data(empty_outcome))

    def test_presales_denial_archives_project_and_records_outcome(self):
        project = self.create_project("presales", name="否决售前项目")
        response = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "early-approval", "outcome": "denied", "note": "投入产出不符合要求"},
        ), project.id)
        self.assertEqual(response.status_code, 200, self.data(response))
        project.refresh_from_db()
        self.assertEqual(project.status, ServiceProject.STATUS_CANCELLED)
        node = project.nodes.get(node_key="early-approval")
        self.assertEqual(node.business_data["outcome"], "denied")
        self.assertEqual(project.business_data["terminalNodeKey"], "early-approval")

    def test_aftersales_selection_and_project_reopen_follow_workflow_rules(self):
        project = self.create_project("aftersales")
        switched = views.project_select_service(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/select-service",
            {"nodeKey": "mail-service", "note": "改为寄件维修"},
        ), project.id)
        self.assertEqual(switched.status_code, 200, self.data(switched))
        project.refresh_from_db()
        self.assertEqual(project.current_node_key, "mail-service")
        self.assertEqual(project.nodes.filter(enabled=True).count(), 1)
        self.assertEqual(project.nodes.get(node_key="mail-service").status, ProjectNode.STATUS_PENDING)

        started = views.project_start(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/start",
            {"nodeKey": "mail-service"},
        ), project.id)
        self.assertEqual(started.status_code, 200, self.data(started))

        node = project.nodes.get(node_key="mail-service")
        for category, _label in PrivateAttachment.CATEGORY_CHOICES:
            if category not in {
                PrivateAttachment.CATEGORY_PACKAGE,
                PrivateAttachment.CATEGORY_MODEL_LABEL,
                PrivateAttachment.CATEGORY_APPEARANCE,
                PrivateAttachment.CATEGORY_INSTALLATION,
                PrivateAttachment.CATEGORY_DEBUGGING,
            }:
                continue
            PrivateAttachment.objects.create(
                target_type=PrivateAttachment.TARGET_PROJECT_NODE,
                target_id=node.id,
                category=category,
                file=f"tests/{category}.jpg",
                original_name=f"{category}.jpg",
                mime_type="image/jpeg",
                size=10,
                uploaded_by="system-admin",
            )
        completed = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {
                "nodeKey": "mail-service",
                "note": "维修完成",
                "businessData": {
                    "actualStartTime": "2026-07-30 09:00",
                    "actualDuration": "4小时",
                },
            },
        ), project.id)
        self.assertEqual(completed.status_code, 200, self.data(completed))
        project.refresh_from_db()
        self.assertEqual(project.status, ServiceProject.STATUS_COMPLETED)

        reopened = views.project_reopen(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/reopen",
            {"nodeKey": "mail-service", "note": "客户要求复检"},
        ), project.id)
        self.assertEqual(reopened.status_code, 200, self.data(reopened))
        project.refresh_from_db()
        self.assertEqual(project.status, ServiceProject.STATUS_IN_PROGRESS)
        self.assertEqual(project.current_node_key, "mail-service")
        self.assertEqual(project.nodes.get(node_key="mail-service").status, ProjectNode.STATUS_ACTIVE)

        midsales = self.create_project("midsales", name="节点退回测试")
        first_key = midsales.current_node_key
        views.project_advance(self.request(
            "post", f"/api/after-sales/projects/{midsales.id}/advance", {"nodeKey": first_key},
        ), midsales.id)
        midsales.refresh_from_db()
        response = views.project_reopen(self.request(
            "post", f"/api/after-sales/projects/{midsales.id}/reopen", {"nodeKey": first_key, "note": "立项资料补充"},
        ), midsales.id)
        self.assertEqual(response.status_code, 200, self.data(response))
        midsales.refresh_from_db()
        self.assertEqual(midsales.current_node_key, first_key)
        self.assertEqual(midsales.nodes.get(node_key=first_key).status, ProjectNode.STATUS_ACTIVE)

    def test_midsales_nodes_start_and_close_sequentially(self):
        project = self.create_project("midsales", name="售中顺序节点")
        self.assertEqual(project.nodes.get(node_key="device-install").status, ProjectNode.STATUS_PENDING)

        first = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "midsales-project"},
        ), project.id)
        self.assertEqual(first.status_code, 200, self.data(first))
        project.refresh_from_db()

        for node_key in [
            "construction-work", "furniture-install", "device-install",
            "device-debug", "school-support", "project-acceptance",
        ]:
            self.assertEqual(project.current_node_key, node_key)
            self.assertEqual(project.nodes.get(node_key=node_key).status, ProjectNode.STATUS_PENDING)
            self.start_midsales_node(project, node_key)
            self.confirm_field_completion(project, node_key)
            response = views.project_advance(self.request(
                "post",
                f"/api/after-sales/projects/{project.id}/advance",
                {"nodeKey": node_key},
            ), project.id)
            self.assertEqual(response.status_code, 200, self.data(response))
            project.refresh_from_db()

        end = project.nodes.get(node_key="midsales-project-end")
        self.assertEqual(end.status, ProjectNode.STATUS_PENDING)
        self.start_midsales_node(project, end.node_key)
        finished = views.project_advance(self.request(
            "post", f"/api/after-sales/projects/{project.id}/advance", {"nodeKey": end.node_key},
        ), project.id)
        self.assertEqual(finished.status_code, 200, self.data(finished))
        project.refresh_from_db()
        self.assertEqual(project.status, ServiceProject.STATUS_COMPLETED)
        self.assertIsNotNone(project.actual_end_date)

    def test_submitting_version_persists_values_without_closing_node(self):
        project = self.create_project("midsales", name="版本留痕")
        node = project.nodes.get(node_key="device-debug")
        node.status = ProjectNode.STATUS_ACTIVE
        node.actual_start_at = timezone.now()
        node.actual_fee = Decimal("180.00")
        node.save(update_fields=["status", "actual_start_at", "actual_fee"])
        project.current_node_key = node.node_key
        project.save(update_fields=["current_node_key"])
        response = views.project_submit_version(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/nodes/device-debug/version",
            {
                "plannedStartAt": "2026-08-01T09:00:00+08:00",
                "actualFee": "320.50",
                "note": "联调版本 V1",
            },
        ), project.id, "device-debug")
        self.assertEqual(response.status_code, 200, self.data(response))
        node.refresh_from_db()
        self.assertEqual(node.status, ProjectNode.STATUS_ACTIVE)
        self.assertEqual(node.actual_fee, Decimal("180.00"))
        self.assertEqual(node.business_data["versionNumber"], 1)
        self.assertTrue(ProjectEvent.objects.filter(
            project=project,
            node=node,
            event_type="node_version_submitted",
        ).exists())

    def test_autosaving_node_draft_persists_without_creating_version_history(self):
        project = self.create_project("midsales", name="自动保存草稿")
        node = project.nodes.get(node_key="device-debug")
        node.actual_fee = Decimal("210.00")
        node.business_data = {"feeActualNote": "现场人员填写的实际费用说明"}
        node.save(update_fields=["actual_fee", "business_data"])
        event_count = ProjectEvent.objects.filter(project=project).count()

        response = views.project_node_autosave(self.request(
            "patch",
            f"/api/after-sales/projects/{project.id}/nodes/device-debug",
            {
                "plannedStartAt": "2026-08-01T09:00:00+08:00",
                "plannedEndAt": "2026-08-02T18:00:00+08:00",
                "estimatedFee": "500.00",
                "actualFee": "320.50",
                "businessData": {
                    "deliveryNote": "已完成联调，等待客户确认",
                    "feeActualNote": "实际使用两名工程师",
                },
            },
        ), project.id, "device-debug")

        self.assertEqual(response.status_code, 200, self.data(response))
        node.refresh_from_db()
        self.assertEqual(node.status, ProjectNode.STATUS_PENDING)
        self.assertEqual(node.estimated_fee, Decimal("500.00"))
        self.assertEqual(node.actual_fee, Decimal("210.00"))
        self.assertEqual(node.business_data["deliveryNote"], "已完成联调，等待客户确认")
        self.assertEqual(node.business_data["feeActualNote"], "现场人员填写的实际费用说明")
        self.assertNotIn("versionNumber", node.business_data)
        self.assertEqual(ProjectEvent.objects.filter(project=project).count(), event_count)

    def test_aftersales_completion_can_be_rejected_for_rework(self):
        project = self.create_project("aftersales", name="售后返工")
        node = project.nodes.get(enabled=True)
        node.status = ProjectNode.STATUS_ACTIVE
        node.save(update_fields=["status"])
        response = views.project_reject_completion(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/reject-completion",
            {"nodeKey": node.node_key, "note": "安装照片无法看清设备编号"},
        ), project.id)
        self.assertEqual(response.status_code, 200, self.data(response))
        node.refresh_from_db()
        self.assertEqual(node.status, ProjectNode.STATUS_ACTIVE)
        self.assertEqual(node.business_data["managerReviewStatus"], "rejected")
        self.assertEqual(node.business_data["managerReviewNote"], "安装照片无法看清设备编号")

    def test_terminal_presales_outcome_can_be_restored(self):
        project = self.create_project("presales", name="售前恢复")
        denied = views.project_advance(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": "early-approval", "outcome": "denied", "note": "资料不足"},
        ), project.id)
        self.assertEqual(denied.status_code, 200, self.data(denied))

        restored = views.project_reopen(self.request(
            "post",
            f"/api/after-sales/projects/{project.id}/reopen",
            {"nodeKey": "early-approval", "note": "资料已补齐"},
        ), project.id)
        self.assertEqual(restored.status_code, 200, self.data(restored))
        project.refresh_from_db()
        node = project.nodes.get(node_key="early-approval")
        self.assertEqual(project.status, ServiceProject.STATUS_IN_PROGRESS)
        self.assertEqual(node.status, ProjectNode.STATUS_ACTIVE)
        self.assertNotIn("outcome", node.business_data)
        self.assertNotIn("terminalOutcome", project.business_data)


class TicketAndFeedbackTests(CleanDomainMixin, RequestMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.clear_domain()
        self.provider = ServiceProvider.objects.create(
            auth_user_id="provider-a",
            name="张师傅",
            role="installer",
            certification_status="certified",
        )
        create_response = views.projects_collection(self.request(
            "post",
            "/api/after-sales/projects",
            {
                "serviceType": "aftersales",
                "name": "浙江工商大学售后",
                "customer": "浙江工商大学",
                "ownerName": "项目经理-陈明",
                "address": "杭州项目现场",
                "businessData": AFTERSALES_DISPATCH_DATA,
            },
        ))
        self.project = ServiceProject.objects.get(pk=self.data(create_response)["item"]["id"])
        views.project_assignments(self.request(
            "post",
            f"/api/after-sales/projects/{self.project.id}/assignments",
            {"nodeKey": self.project.current_node_key, "providerId": self.provider.id},
        ), self.project.id)

    def provider_request(self, method, path, payload=None):
        return self.request(method, path, payload, user_id="provider-a", name="张师傅", admin=False)

    def create_ticket(self):
        response = views.tickets_collection(self.provider_request(
            "post",
            "/api/after-sales/tickets",
            {
                "projectId": self.project.id,
                "nodeKey": self.project.current_node_key,
                "title": "平台接入权限异常",
                "ticketType": "资料权限",
                "priority": "high",
                "description": "现场账号提示无权限。",
            },
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        return ServiceTicket.objects.get(pk=self.data(response)["item"]["id"])

    def test_completed_assignment_can_create_ticket_and_feedback(self):
        assignment = ProjectAssignment.objects.get(
            project=self.project,
            node__node_key=self.project.current_node_key,
            provider=self.provider,
        )
        assignment.status = ProjectAssignment.STATUS_COMPLETED
        assignment.completed_at = timezone.now()
        assignment.save(update_fields=["status", "completed_at"])

        ticket_response = views.tickets_collection(self.provider_request(
            "post",
            "/api/after-sales/tickets",
            {
                "projectId": self.project.id,
                "nodeKey": self.project.current_node_key,
                "title": "完工后补充工单",
                "ticketType": "现场问题",
                "priority": "low",
                "description": "完工后发现需要继续跟进的问题。",
            },
        ))
        self.assertEqual(ticket_response.status_code, 201, self.data(ticket_response))
        self.assertEqual(
            self.data(ticket_response)["item"]["nodeName"],
            self.project.nodes.get(node_key=self.project.current_node_key).name,
        )

        feedback_response = views.feedback_collection(self.provider_request(
            "post",
            "/api/after-sales/feedback",
            {
                "projectId": self.project.id,
                "nodeKey": self.project.current_node_key,
                "feedbackType": "issue",
                "content": "完工后补充现场反馈。",
            },
        ))
        self.assertEqual(feedback_response.status_code, 201, self.data(feedback_response))
        self.assertEqual(
            self.data(feedback_response)["item"]["nodeName"],
            self.project.nodes.get(node_key=self.project.current_node_key).name,
        )

    def test_ticket_state_machine_and_messages(self):
        ticket = self.create_ticket()
        edited = views.ticket_item(self.request(
            "patch",
            f"/api/after-sales/tickets/{ticket.id}",
            {
                "title": "平台账号权限异常",
                "priority": "medium",
                "ownerUserId": "handler-a",
                "ownerName": "处理人甲",
            },
        ), ticket.id)
        self.assertEqual(edited.status_code, 200, self.data(edited))
        ticket.refresh_from_db()
        self.assertEqual(ticket.title, "平台账号权限异常")
        self.assertEqual(ticket.owner_user_id, "handler-a")
        self.assertEqual(ticket.owner_name, "处理人甲")

        message = views.ticket_messages(self.provider_request(
            "post",
            f"/api/after-sales/tickets/{ticket.id}/messages",
            {"content": "现场已补充复现步骤。"},
        ), ticket.id)
        self.assertEqual(message.status_code, 201, self.data(message))
        self.assertEqual(self.data(message)["item"]["content"], "现场已补充复现步骤。")

        invalid = views.ticket_transition(self.request(
            "post",
            f"/api/after-sales/tickets/{ticket.id}/transition",
            {"status": "completed"},
        ), ticket.id)
        self.assertEqual(invalid.status_code, 409)
        self.assertEqual(self.data(invalid)["code"], "INVALID_TICKET_TRANSITION")

        for status, admin in [
            ("assigned", True),
            ("in_progress", False),
            ("pending_review", False),
        ]:
            request = self.request(
                "post",
                f"/api/after-sales/tickets/{ticket.id}/transition",
                {"status": status, "note": f"进入 {status}"},
                user_id="system-admin" if admin else "provider-a",
                name="管理员" if admin else "张师傅",
                admin=admin,
            )
            response = views.ticket_transition(request, ticket.id)
            self.assertEqual(response.status_code, 200, self.data(response))

        provider_complete = views.ticket_transition(self.provider_request(
            "post",
            f"/api/after-sales/tickets/{ticket.id}/transition",
            {"status": "completed"},
        ), ticket.id)
        self.assertEqual(provider_complete.status_code, 403)

        completed = views.ticket_transition(self.request(
            "post",
            f"/api/after-sales/tickets/{ticket.id}/transition",
            {"status": "completed", "note": "技术复核通过"},
        ), ticket.id)
        self.assertEqual(completed.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, ServiceTicket.STATUS_COMPLETED)
        self.assertGreaterEqual(ticket.messages.count(), 5)

        removed_status = views.ticket_transition(self.request(
            "post",
            f"/api/after-sales/tickets/{ticket.id}/transition",
            {"status": "closed"},
        ), ticket.id)
        self.assertEqual(removed_status.status_code, 400, self.data(removed_status))
        self.assertEqual(self.data(removed_status)["code"], "INVALID_CHOICE")

    def test_reward_transition_locks_reward_without_nullable_project_join(self):
        self.provider.city = "杭州"
        self.provider.save(update_fields=["city"])
        reward = Reward.objects.create(
            code="RW-TRANSITION-TEST",
            provider=self.provider,
            title="状态流转测试奖励",
            reward_type=Reward.TYPE_PRIZE,
            prize="测试礼品",
        )

        response = views.reward_transition(self.request(
            "post",
            f"/api/after-sales/rewards/{reward.id}/transition",
            {"status": Reward.STATUS_APPROVED, "note": "审核通过"},
        ), reward.id)

        self.assertEqual(response.status_code, 200, self.data(response))
        reward.refresh_from_db()
        self.assertEqual(reward.status, Reward.STATUS_APPROVED)
        self.assertEqual(reward.transition_note, "审核通过")
        listing = views.rewards_collection(self.request(
            "get",
            "/api/after-sales/rewards",
            query={"page_size": 10},
        ))
        listed = next(item for item in self.data(listing)["items"] if item["id"] == reward.id)
        self.assertEqual(listed["providerCity"], "杭州")

    def test_new_reward_defaults_to_pending_and_uses_provider_city(self):
        self.provider.city = "宁波"
        self.provider.save(update_fields=["city"])
        prize = RewardPrize.objects.create(name="工具包")
        response = views.rewards_collection(self.request(
            "post",
            "/api/after-sales/rewards",
            {
                "providerId": self.provider.id,
                "rewardType": Reward.TYPE_PRIZE,
                "title": "服务表现奖励",
                "prizeId": prize.id,
            },
        ))

        self.assertEqual(response.status_code, 201, self.data(response))
        item = self.data(response)["item"]
        self.assertEqual(item["status"], Reward.STATUS_PENDING)
        self.assertEqual(item["statusLabel"], "待审核")
        self.assertEqual(item["providerCity"], "宁波")
        self.assertEqual(item["prize"], "工具包")

    def test_manual_reward_requires_active_prize_from_catalog(self):
        prize = RewardPrize.objects.create(name="工具包")
        base = {"providerId": self.provider.id, "title": "服务表现奖励", "rewardType": Reward.TYPE_PRIZE}
        for fields in (
            {"prize": "自由输入的奖品"},
            {"prizeId": 987654},
            {"prizeId": prize.id + 1, "prize": "工具包"},
        ):
            with self.subTest(fields=fields):
                response = views.rewards_collection(self.request(
                    "post", "/api/after-sales/rewards", {**base, **fields},
                ))
                self.assertEqual(response.status_code, 400, self.data(response))
                self.assertEqual(self.data(response)["code"], "INVALID_REWARD_PRIZE")

        saved = views.rewards_collection(self.request(
            "post", "/api/after-sales/rewards", {**base, "prizeId": prize.id, "prize": "伪造名称"},
        ))
        self.assertEqual(saved.status_code, 201, self.data(saved))
        reward_id = self.data(saved)["item"]["id"]
        self.assertEqual(self.data(saved)["item"]["prize"], "工具包")

        prize.name = "升级工具包"
        prize.enabled = False
        prize.save(update_fields=["name", "enabled"])
        denied = views.rewards_collection(self.request(
            "post", "/api/after-sales/rewards", {**base, "prizeId": prize.id},
        ))
        self.assertEqual(denied.status_code, 400, self.data(denied))
        self.assertEqual(Reward.objects.get(pk=reward_id).prize, "工具包")

    def test_other_reward_types_do_not_require_catalog(self):
        for reward_type, fields in (
            (Reward.TYPE_CASH, {"amount": "20.00"}),
            (Reward.TYPE_TIME_OFF, {"prize": "调休半天"}),
        ):
            with self.subTest(reward_type=reward_type):
                response = views.rewards_collection(self.request(
                    "post", "/api/after-sales/rewards",
                    {"providerId": self.provider.id, "rewardType": reward_type, "title": "奖励", **fields},
                ))
                self.assertEqual(response.status_code, 201, self.data(response))

    def test_points_cannot_be_created_but_existing_rewards_remain_visible(self):
        for payload in (
            {"rewardType": Reward.TYPE_POINTS},
            {"rewardType": Reward.TYPE_PRIZE, "points": 50},
        ):
            with self.subTest(payload=payload):
                response = views.rewards_collection(self.request(
                    "post",
                    "/api/after-sales/rewards",
                    {"providerId": self.provider.id, "title": "测试奖励", **payload},
                ))
                self.assertEqual(response.status_code, 400, self.data(response))
                self.assertEqual(self.data(response)["code"], "INVALID_CHOICE")
        self.assertFalse(Reward.objects.exists())

        legacy = Reward.objects.create(
            code="RW-LEGACY-POINTS", provider=self.provider,
            reward_type=Reward.TYPE_POINTS, title="历史积分奖励", points=50,
        )
        listing = views.rewards_collection(self.request("get", "/api/after-sales/rewards"))
        item = next(row for row in self.data(listing)["items"] if row["id"] == legacy.id)
        self.assertEqual(item["rewardTypeLabel"], "积分奖励")
        self.assertEqual(item["points"], 50)

    def test_feedback_review_creates_one_reward(self):
        prize = RewardPrize.objects.create(name="纪念礼品")
        response = views.feedback_collection(self.provider_request(
            "post",
            "/api/after-sales/feedback",
            {
                "projectId": self.project.id,
                "nodeKey": self.project.current_node_key,
                "feedbackType": "resource_suggestion",
                "content": "建议增加账号权限检查清单。",
                "rating": 5,
            },
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        feedback = FieldFeedback.objects.get(pk=self.data(response)["item"]["id"])
        review = views.feedback_review(self.request(
            "post",
            f"/api/after-sales/feedback/{feedback.id}/review",
            {
                "decision": "accepted",
                "reviewNote": "建议有效，纳入资料维护。",
                "reward": {"rewardType": "prize", "title": "建议采纳奖励", "prizeId": prize.id},
            },
        ), feedback.id)
        self.assertEqual(review.status_code, 200, self.data(review))
        feedback.refresh_from_db()
        self.assertTrue(feedback.reward_generated)
        reward = Reward.objects.get(feedback=feedback)
        self.assertEqual(reward.reward_type, Reward.TYPE_PRIZE)
        self.assertEqual(reward.prize, "纪念礼品")

        duplicate = views.feedback_review(self.request(
            "post",
            f"/api/after-sales/feedback/{feedback.id}/review",
            {"status": "accepted"},
        ), feedback.id)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(Reward.objects.filter(feedback=feedback).count(), 1)

    def test_feedback_review_rejects_points_without_reviewing_feedback(self):
        response = views.feedback_collection(self.provider_request(
            "post", "/api/after-sales/feedback",
            {"projectId": self.project.id, "nodeKey": self.project.current_node_key,
             "feedbackType": "resource_suggestion", "content": "建议补充服务规范。"},
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        feedback = FieldFeedback.objects.get(pk=self.data(response)["item"]["id"])
        for reward in (
            {"rewardType": Reward.TYPE_POINTS, "title": "积分", "points": 50},
            {"rewardType": Reward.TYPE_PRIZE, "title": "实物", "points": 50},
        ):
            with self.subTest(reward=reward):
                review = views.feedback_review(self.request(
                    "post", f"/api/after-sales/feedback/{feedback.id}/review",
                    {"decision": "accepted", "reward": reward},
                ), feedback.id)
                self.assertEqual(review.status_code, 400, self.data(review))
                self.assertEqual(self.data(review)["code"], "INVALID_CHOICE")
                feedback.refresh_from_db()
                self.assertEqual(feedback.status, FieldFeedback.STATUS_SUBMITTED)
                self.assertFalse(Reward.objects.filter(feedback=feedback).exists())

    def test_admin_with_provider_profile_can_submit_own_feedback(self):
        response = views.feedback_collection(self.request(
            "post",
            "/api/after-sales/feedback",
            {
                "projectId": self.project.id,
                "nodeKey": self.project.current_node_key,
                "feedbackType": "resource_suggestion",
                "content": "管理员现场账号提交的资料建议。",
            },
            user_id="provider-a",
            name="张师傅",
            admin=True,
        ))

        self.assertEqual(response.status_code, 201, self.data(response))
        self.assertEqual(self.data(response)["item"]["providerId"], self.provider.id)

    def test_feedback_list_can_filter_by_project(self):
        own = FieldFeedback.objects.create(
            project=self.project,
            node=self.project.nodes.get(node_key=self.project.current_node_key),
            provider=self.provider,
            feedback_type=FieldFeedback.TYPE_RESOURCE,
            title="当前项目反馈",
            content="当前项目内容",
        )
        other_project = ServiceProject.objects.create(
            code="OTHER-FEEDBACK-PROJECT",
            service_type=ServiceProject.TYPE_AFTERSALES,
            name="其他项目",
            customer="其他客户",
        )
        FieldFeedback.objects.create(
            project=other_project,
            provider=self.provider,
            feedback_type=FieldFeedback.TYPE_RESOURCE,
            title="其他项目反馈",
            content="其他项目内容",
        )

        response = views.feedback_collection(self.request(
            "get",
            "/api/after-sales/feedback",
            query={"projectId": self.project.id, "page_size": 100},
        ))

        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertEqual([item["id"] for item in self.data(response)["items"]], [own.id])
        self.assertEqual(self.data(response)["items"][0]["nodeName"], own.node.name)


class MobileIsolationTests(CleanDomainMixin, RequestMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.clear_domain()
        self.providers = []
        for user_id, name in [("provider-a", "张师傅"), ("provider-b", "李工")]:
            self.providers.append(ServiceProvider.objects.create(
                auth_user_id=user_id,
                name=name,
                role="installer",
                certification_status="certified",
            ))

    def admin_request(self, method, path, payload=None):
        return self.request(method, path, payload)

    def create_assigned_project(self, provider, name):
        response = views.projects_collection(self.admin_request(
            "post",
            "/api/after-sales/projects",
            {"serviceType": "midsales", "name": name, "customer": name},
        ))
        project = ServiceProject.objects.get(pk=self.data(response)["item"]["id"])
        advance = views.project_advance(self.admin_request(
            "post",
            f"/api/after-sales/projects/{project.id}/advance",
            {"nodeKey": project.current_node_key},
        ), project.id)
        self.assertEqual(advance.status_code, 200, self.data(advance))
        project.refresh_from_db()
        views.project_assignments(self.admin_request(
            "post",
            f"/api/after-sales/projects/{project.id}/assignments",
            {"nodeKey": project.current_node_key, "providerId": provider.id},
        ), project.id)
        started = views.project_start(self.admin_request(
            "post",
            f"/api/after-sales/projects/{project.id}/start",
            {"nodeKey": project.current_node_key},
        ), project.id)
        self.assertEqual(started.status_code, 200, self.data(started))
        return project

    def test_mobile_home_only_contains_current_users_data(self):
        project_a = self.create_assigned_project(self.providers[0], "甲项目")
        project_b = self.create_assigned_project(self.providers[1], "乙项目")
        ServiceResource.objects.create(
            project=project_a,
            node_key=project_a.current_node_key,
            title="甲项目资料",
            resource_type="manual",
            audience="assigned",
        )
        ServiceResource.objects.create(
            project=project_a,
            node_key="furniture-install",
            title="甲项目其他节点资料",
            resource_type="manual",
            audience="assigned",
        )
        ServiceResource.objects.create(
            project=project_b,
            node_key=project_b.current_node_key,
            title="乙项目资料",
            resource_type="manual",
            audience="assigned",
        )
        ServiceResource.objects.create(title="公开资料", resource_type="video", audience="public")
        feedback_a = FieldFeedback.objects.create(
            project=project_a,
            node=project_a.nodes.get(node_key=project_a.current_node_key),
            provider=self.providers[0],
            feedback_type="issue",
            content="甲反馈",
        )
        FieldFeedback.objects.create(
            project=project_b,
            node=project_b.nodes.get(node_key=project_b.current_node_key),
            provider=self.providers[1],
            feedback_type="issue",
            content="乙反馈",
        )
        FieldFeedback.objects.create(
            project=project_a,
            node=project_a.nodes.get(node_key="construction-work"),
            provider=self.providers[1],
            feedback_type="issue",
            content="甲项目其他人员反馈",
        )
        ServiceTicket.objects.create(
            code="TK-A-CURRENT",
            project=project_a,
            node=project_a.nodes.get(node_key=project_a.current_node_key),
            title="甲项目当前节点工单",
            ticket_type="现场异常",
            reporter_user_id="provider-b",
            description="当前节点问题",
        )
        ServiceTicket.objects.create(
            code="TK-A-OTHER",
            project=project_a,
            node=project_a.nodes.get(node_key="furniture-install"),
            title="甲项目其他节点工单",
            ticket_type="现场异常",
            reporter_user_id="provider-b",
            description="其他节点问题",
        )
        Reward.objects.create(
            code="RW-A",
            provider=self.providers[0],
            project=project_a,
            feedback=feedback_a,
            reward_type="points",
            title="甲奖励",
        )
        Reward.objects.create(code="RW-B", provider=self.providers[1], project=project_b, reward_type="prize", title="乙奖励")

        response = views.mobile_home(self.request(
            "get",
            "/api/after-sales/mobile/home",
            user_id="provider-a",
            name="张师傅",
            admin=False,
        ))
        self.assertEqual(response.status_code, 200, self.data(response))
        data = self.data(response)
        self.assertEqual({row["project"]["name"] for row in data["tasks"]}, {"甲项目"})
        task = data["tasks"][0]
        expected_compact_node_fields = {
            "id", "nodeKey", "name", "status", "statusLabel", "description",
            "plannedStartAt", "plannedEndAt", "actualStartAt", "actualEndAt",
            "estimatedFee", "actualFee", "businessData",
        }
        self.assertEqual(set(task["node"]), expected_compact_node_fields | {
            "settlementId", "settlementStatus", "settlementStatusLabel",
        })
        self.assertEqual(project_a.nodes.count(), len(task["nodes"]))
        self.assertEqual(
            set(project_a.nodes.values_list("node_key", flat=True)),
            {row["nodeKey"] for row in task["nodes"]},
        )
        self.assertTrue(all(set(row) == expected_compact_node_fields for row in task["nodes"]))
        self.assertEqual({row["title"] for row in data["resources"]}, {"甲项目资料", "公开资料"})
        self.assertEqual({row["content"] for row in data["feedback"]}, {"甲反馈"})
        self.assertEqual({row["title"] for row in data["rewards"]}, {"甲奖励"})
        self.assertEqual({row["title"] for row in data["tickets"]}, {"甲项目当前节点工单"})

        dashboard = views.dashboard(self.request(
            "get",
            "/api/after-sales/dashboard",
            user_id="provider-a",
            name="张师傅",
            admin=False,
        ))
        dashboard_data = self.data(dashboard)
        self.assertEqual(dashboard_data["metrics"]["openTickets"], 1)
        self.assertEqual(dashboard_data["metrics"]["pendingFeedback"], 1)

    def test_dashboard_returns_scoped_active_tasks_and_three_risk_types(self):
        project_a = self.create_assigned_project(self.providers[0], "甲风险项目")
        project_b = self.create_assigned_project(self.providers[1], "乙风险项目")
        project_b.owner_user_id = "other-admin"
        project_b.created_by = "other-admin"
        project_a.status = ServiceProject.STATUS_BLOCKED
        project_b.status = ServiceProject.STATUS_BLOCKED
        project_a.save(update_fields=["status"])
        project_b.save(update_fields=["owner_user_id", "created_by", "status"])

        node_a = project_a.nodes.get(node_key=project_a.current_node_key)
        node_b = project_b.nodes.get(node_key=project_b.current_node_key)
        node_a.planned_end_at = timezone.now() - timedelta(days=2)
        node_b.planned_end_at = timezone.now() - timedelta(days=1)
        node_a.save(update_fields=["planned_end_at"])
        node_b.save(update_fields=["planned_end_at"])
        ServiceTicket.objects.create(
            code="TK-DASH-A",
            project=project_a,
            node=node_a,
            title="甲项目紧急工单",
            ticket_type="现场异常",
            priority=ServiceTicket.PRIORITY_HIGH,
            reporter_user_id="reporter-a",
            description="需要立即处理",
        )
        ServiceTicket.objects.create(
            code="TK-DASH-B",
            project=project_b,
            node=node_b,
            title="乙项目紧急工单",
            ticket_type="现场异常",
            priority=ServiceTicket.PRIORITY_HIGH,
            reporter_user_id="reporter-b",
            description="其他服务商处理",
        )

        response = views.dashboard(self.request(
            "get",
            "/api/after-sales/dashboard",
            user_id="provider-a",
            name="张师傅",
            admin=False,
        ))
        self.assertEqual(response.status_code, 200, self.data(response))
        payload = self.data(response)
        self.assertEqual([row["projectId"] for row in payload["tasks"]], [project_a.id])
        self.assertEqual(payload["tasks"][0]["nodeId"], node_a.id)
        self.assertEqual(payload["tasks"][0]["module"], ServiceProject.TYPE_MIDSALES)
        self.assertIn("已超时", payload["tasks"][0]["dueText"])
        self.assertEqual(
            {(row["type"], row["projectId"]) for row in payload["alerts"]},
            {
                ("blocked_project", project_a.id),
                ("overdue_node", project_a.id),
                ("high_priority_ticket", project_a.id),
            },
        )

        admin_response = views.dashboard(self.request("get", "/api/after-sales/dashboard"))
        self.assertEqual(admin_response.status_code, 200, self.data(admin_response))
        admin_payload = self.data(admin_response)
        self.assertEqual(admin_payload["scope"], "business")
        self.assertEqual(admin_payload["taskTotal"], 0)
        self.assertEqual(admin_payload["tasks"], [])
        self.assertEqual({row["id"] for row in admin_payload["recentProjects"]}, {project_a.id, project_b.id})
        self.assertEqual(
            {(row["type"], row["projectId"]) for row in admin_payload["alerts"]},
            {
                ("blocked_project", project_a.id),
                ("overdue_node", project_a.id),
                ("high_priority_ticket", project_a.id),
                ("blocked_project", project_b.id),
                ("overdue_node", project_b.id),
                ("high_priority_ticket", project_b.id),
            },
        )


class SupportingApiTests(CleanDomainMixin, RequestMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.clear_domain()
        self.provider = ServiceProvider.objects.create(
            auth_user_id="provider-a",
            name="张师傅",
            role="installer",
            certification_status="certified",
        )
        response = views.projects_collection(self.request(
            "post", "/api/after-sales/projects",
            {
                "serviceType": "aftersales",
                "name": "售后项目",
                "customer": "客户",
                "ownerName": "项目经理-陈明",
                "address": "杭州项目现场",
                "businessData": AFTERSALES_DISPATCH_DATA,
            },
        ))
        self.project = ServiceProject.objects.get(pk=self.data(response)["item"]["id"])
        views.project_assignments(self.request(
            "post", f"/api/after-sales/projects/{self.project.id}/assignments",
            {"nodeKey": self.project.current_node_key, "providerId": self.provider.id},
        ), self.project.id)

    def test_settlement_and_resource_apis(self):
        source_node = self.project.nodes.get(node_key=self.project.current_node_key)
        source_node.status = ProjectNode.STATUS_COMPLETED
        source_node.estimated_fee = "1200.00"
        source_node.actual_fee = "1200.00"
        source_node.business_data = {**(source_node.business_data or {}), "externalQuote": "1500.00"}
        source_node.save(update_fields=["status", "estimated_fee", "actual_fee", "business_data"])
        source_assignment = self.project.assignments.get(node=source_node)
        source_assignment.status = ProjectAssignment.STATUS_COMPLETED
        source_assignment.save(update_fields=["status"])
        settlement = views.settlements_collection(self.request(
            "post", "/api/after-sales/settlements",
            {
                "projectId": self.project.id,
                "sourceNodeId": source_node.id,
                "sourceAssignmentId": source_assignment.id,
                "bearer": "customer",
                "serviceContent": "上门售后服务费",
                "budgetAmount": "1200",
                "finalAmount": "1200",
            },
        ))
        self.assertEqual(settlement.status_code, 201, self.data(settlement))
        settlement_id = self.data(settlement)["item"]["id"]
        updated = views.settlement_item(self.request(
            "patch", f"/api/after-sales/settlements/{settlement_id}", {"status": "pending", "receivedAmount": "600", "expectedRevision": 1},
        ), settlement_id)
        self.assertEqual(updated.status_code, 200, self.data(updated))
        self.assertEqual(Settlement.objects.get(pk=settlement_id).status, "pending")

        invalid_resource = views.resources_collection(self.request(
            "post", "/api/after-sales/resources",
            {
                "projectId": self.project.id,
                "nodeKey": self.project.current_node_key,
                "title": "不安全外链",
                "resourceType": "manual",
                "audience": "assigned",
                "externalUrl": "javascript:alert(1)",
            },
        ))
        self.assertEqual(invalid_resource.status_code, 400, self.data(invalid_resource))
        self.assertEqual(self.data(invalid_resource)["code"], "INVALID_URL")

        resource = views.resources_collection(self.request(
            "post", "/api/after-sales/resources",
            {
                "projectId": self.project.id,
                "nodeKey": self.project.current_node_key,
                "title": "上门售后资料",
                "resourceType": "manual",
                "audience": "assigned",
                "externalUrl": "https://support.example.test/manual",
            },
        ))
        self.assertEqual(resource.status_code, 201, self.data(resource))
        resource_id = self.data(resource)["item"]["id"]
        resource_detail = views.resource_item(self.request(
            "get", f"/api/after-sales/resources/{resource_id}",
        ), resource_id)
        self.assertEqual(resource_detail.status_code, 200, self.data(resource_detail))
        self.assertEqual(self.data(resource_detail)["item"]["externalUrl"], "https://support.example.test/manual")
        authorized = views.resource_item(self.request(
            "patch",
            f"/api/after-sales/resources/{resource_id}",
            {"action": "authorize", "note": "仅向当前节点人员开放"},
        ), resource_id)
        self.assertEqual(authorized.status_code, 200, self.data(authorized))
        self.assertEqual(ServiceResource.objects.get(pk=resource_id).authorization_note, "仅向当前节点人员开放")
