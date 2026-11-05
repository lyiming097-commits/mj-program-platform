from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import crm_source, services, views
from .models import AppPermissionRule, PrivateAttachment, ProjectNode, ServiceProject
from .presales_task_schedule import sync_presales_task_schedules
from .presales_statistics import _number, presales_statistics
from .tests import CleanDomainMixin, RequestMixin


class PresalesStatisticsTests(RequestMixin, CleanDomainMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.clear_domain()
        cache.clear()
        self.addCleanup(cache.clear)

    def project(self, code, *, source="", snapshot=None, info=None, owner="sales-a", name="销售甲"):
        return services.create_project(self.request("post", "/"), {
            "code": code, "name": code, "customer": "测试学校", "service_type": "presales",
            "owner_user_id": owner, "owner_name": name, "source_crm_id": source,
            "crm_snapshot": snapshot or {}, "business_data": {"projectInfo": info or {}},
        })

    def listing(self, *, allowed=(), admin=True, **query):
        request = self.request("get", "/api/after-sales/presales/statistics", query=query, admin=admin)
        crm_source._remember_scope(request, list(allowed), synced=True)
        with patch.object(views, "sync_crm_presales"), CaptureQueriesContext(connection) as queries:
            response = presales_statistics(request)
        return response, len(queries)

    def test_all_projects_are_counted_before_detail_pagination_and_deleted_or_other_types_are_excluded(self):
        for index in range(24):
            self.project(f"统计项目-{index}", info={"nature": ["设备"], "amount": "0.02", "area": "12.5"})
        removed = self.project("已删除项目", info={"amount": "99999"})
        removed.deleted_at = timezone.now()
        removed.save(update_fields=["deleted_at"])
        ServiceProject.objects.create(code="MS-STATS", name="售中项目", service_type="midsales")
        response, query_count = self.listing(groupBy="nature", page=2, pageSize=20)
        self.assertEqual(response.status_code, 200, self.data(response))
        payload = self.data(response)
        self.assertEqual((payload["summary"]["count"], payload["total"], len(payload["items"])), (24, 24, 4))
        self.assertEqual(payload["summary"]["amount"], "0.48")
        self.assertEqual(payload["summary"]["area"], "300.00")
        self.assertEqual(payload["groups"][0]["count"], 24)
        self.assertLessEqual(query_count, 9)

    def test_default_all_view_is_ungrouped_and_ignores_a_stale_group_key(self):
        first = self.project("全部视图-甲", info={"nature": ["设备", "家具"]})
        second = self.project("全部视图-乙")
        response, _ = self.listing(groupKey="nature:设备")
        payload = self.data(response)
        self.assertEqual(payload["groupBy"], "all")
        self.assertEqual(payload["groups"], [])
        self.assertEqual(payload["total"], 2)
        self.assertEqual({item["id"] for item in payload["items"]}, {first.id, second.id})

    def test_detail_fields_use_project_sources_and_both_requirement_document_sources(self):
        project = self.project("字段映射", source="fields", snapshot={
            "stage": "方案渗透", "bidTime": "2026-11-20", "integrationEngineeringArea": "999",
        }, info={"info": "建设两间教学空间", "reason": "申请补充说明", "totalArea": "120.25",
                 "designArea": "80", "projectLevel": "重要，金额大", "expectedBidAt": "2026-11-25"})
        early = project.nodes.get(node_key="early-approval")
        early.business_data = {"projectLeads": {"solution": {"userId": "solution", "name": "方案甲"}}}
        early.save(update_fields=["business_data"])
        for category in (PrivateAttachment.CATEGORY_GENERAL, PrivateAttachment.CATEGORY_FEE_ESTIMATED):
            PrivateAttachment.objects.create(target_type="project_node", target_id=early.id,
                category=category, file="test-not-stored.pdf", original_name="测试文档.pdf",
                mime_type="application/pdf", size=12, uploaded_by="test")
        for target_id, category in ((project.pk, "general"), (project.pk, "general"),
                                    (project.pk, "fee_estimated"), (999999, "general")):
            PrivateAttachment.objects.create(target_type="presales_project", target_id=target_id,
                category=category, file="test-not-stored.pdf", original_name="项目需求.pdf",
                mime_type="application/pdf", size=12, uploaded_by="test")
        response, _ = self.listing(groupBy="nature", allowed=["fields"])
        item = self.data(response)["items"][0]
        self.assertEqual(item["description"], "建设两间教学空间")
        self.assertEqual(item["note"], "申请补充说明")
        self.assertEqual(item["expectedBidAt"], "2026-11-25", "the locally entered date takes precedence over CRM bidTime")
        self.assertEqual((item["totalArea"], item["designArea"], item["area"]), ("120.25", "80.00", "999.00"))
        self.assertEqual(item["projectLevel"], "重要，金额大")
        self.assertEqual((item["requirementNodeId"], item["requirementCount"]), (early.id, 3))
        self.assertEqual(item["solutionOwners"], [{"userId": "solution", "name": "方案甲"}])
        project.business_data = {"projectInfo": {}}
        project.save(update_fields=["business_data"])
        response, _ = self.listing(allowed=["fields"])
        item = self.data(response)["items"][0]
        self.assertIsNone(item["totalArea"])
        self.assertIsNone(item["designArea"])
        self.assertEqual(item["projectLevel"], "")
        self.assertEqual(item["expectedBidAt"], "", "missing local dates never fall back to CRM bidTime")

    def test_latest_stage_uses_all_current_nodes_independently_of_crm_stage(self):
        project = self.project("并行阶段项目", source="parallel", snapshot={"stage": "方案渗透"})
        project.nodes.update(status=ProjectNode.STATUS_PENDING)
        project.nodes.filter(node_key__in=["early-plan", "budget-match"]).update(status=ProjectNode.STATUS_ACTIVE)
        project.nodes.filter(node_key="project-filing").update(status=ProjectNode.STATUS_ACTIVE, enabled=False)
        project.current_node_key = "early-plan"
        project.save(update_fields=["current_node_key"])

        response, _ = self.listing(groupBy="stage", allowed=["parallel"])
        payload = self.data(response)
        item = payload["items"][0]
        self.assertEqual(item["nodeNames"], ["前期方案", "预算匹配"])
        self.assertEqual(item["latestStage"], "前期方案、预算匹配")
        self.assertEqual(item["crmStage"], "方案渗透")
        self.assertEqual(payload["groups"][0]["label"], "方案渗透")

        # Finished projects use the recorded current node, even if an old active
        # node remains. Local projects also have a node stage without a CRM stage.
        project.status = ServiceProject.STATUS_COMPLETED
        project.current_node_key = "project-filing"
        project.save(update_fields=["status", "current_node_key"])
        project.nodes.filter(node_key="project-filing").update(status=ProjectNode.STATUS_COMPLETED, enabled=True)
        local = self.project("独立项目")
        response, _ = self.listing(allowed=["parallel"])
        items = {row["id"]: row for row in self.data(response)["items"]}
        self.assertEqual(items[project.id]["latestStage"], "项目申报")
        self.assertEqual(items[project.id]["crmStage"], "方案渗透")
        self.assertEqual(items[local.id]["latestStage"], "前期立项")
        self.assertEqual(items[local.id]["crmStage"], "")

    def test_task_progress_counts_real_enabled_rounds_and_keeps_participant_ids_distinct(self):
        project = self.project("有任务的项目")
        node = project.nodes.get(node_key="early-plan")
        node.business_data = {"schemeRounds": [
            {"plannedStartDate": "2026-10-19", "plannedEndDate": "2026-10-22", "designDate": "2026-10-21"},
            {"plannedEndDate": "2026-10-25"},
        ], "managementAssignment": {"members": [
            {"userId": "first", "name": "同名执行人"}, {"userId": "second", "name": "同名执行人"},
        ]}}
        node.save(update_fields=["business_data"])
        sync_presales_task_schedules(node)
        disabled = project.nodes.get(node_key="project-filing")
        disabled.enabled = False
        disabled.business_data = {"schemeRounds": [{"designDate": "2026-10-20"}]}
        disabled.save(update_fields=["business_data", "enabled"])
        sync_presales_task_schedules(disabled)
        response, _ = self.listing()
        item = self.data(response)["items"][0]
        self.assertEqual((item["taskCount"], item["completedTaskCount"]), (2, 0))
        self.assertTrue(all(not task["isCompleted"] and task["actualEndDate"] is None for task in item["tasks"]))
        self.assertEqual(len(item["earlyTasks"]), 2)
        self.assertEqual(item["filingTasks"], [])
        self.assertEqual(item["tasks"][0]["plannedStartDate"], "2026-10-19")
        self.assertEqual({row["userId"] for row in item["participants"]}, {"first", "second"})
        node.status = ProjectNode.STATUS_COMPLETED
        node.completed_at = timezone.now()
        node.save(update_fields=["status", "completed_at"])
        response, _ = self.listing()
        item = self.data(response)["items"][0]
        self.assertEqual(item["completedTaskCount"], 2)
        self.assertTrue(all(task["isCompleted"] for task in item["tasks"]))
        self.assertEqual(item["tasks"][0]["actualEndDate"], timezone.localdate(node.completed_at).isoformat())

    def test_multivalue_natures_and_multiple_design_owners_never_duplicate_the_global_summary(self):
        project = self.project("交叉分类项目", info={"nature": ["设备", "家具", "设备"], "amount": "100.01"})
        project.nodes.filter(node_key="early-approval").update(business_data={"projectLeads": {"design": {
            "members": [{"userId": "designer-a", "name": "同名设计"}, {"userId": "designer-b", "name": "同名设计"},
                        {"userId": "designer-a", "name": "同名设计"}],
        }}})
        response, _ = self.listing(groupBy="nature")
        data = self.data(response)
        self.assertEqual((data["summary"]["count"], data["groupMembershipCount"]), (1, 2))
        self.assertEqual({row["label"] for row in data["groups"]}, {"设备", "家具"})
        response, _ = self.listing(groupBy="design", groupKey="design:designer-b")
        data = self.data(response)
        self.assertEqual(len(data["groups"]), 2)
        self.assertEqual(data["summary"]["amount"], "100.01")
        self.assertEqual([row["id"] for row in data["items"]], [project.id])

    def test_crm_scope_and_stage_gate_also_protect_statistics(self):
        self.project("允许项目", source="allowed", snapshot={"stage": "方案渗透", "amount": "123.45",
            "integrationWorkTypes": ["设备"], "integrationEngineeringArea": "30"})
        self.project("不可见项目", source="hidden", snapshot={"stage": "方案渗透", "amount": "99999"})
        self.project("尚未进入售前", source="early", snapshot={"stage": "在跟线索", "amount": "88888"})
        response, _ = self.listing(groupBy="stage", allowed=["allowed", "early"])
        self.assertEqual(response.status_code, 200, self.data(response))
        payload = self.data(response)
        self.assertEqual(payload["summary"]["count"], 1)
        self.assertEqual(payload["summary"]["amount"], "123.45")
        self.assertEqual(payload["items"][0]["natures"], ["设备"])
        self.assertEqual(payload["groups"][0]["label"], "方案渗透")

    def test_missing_amounts_stay_missing_but_explicit_zero_is_included(self):
        self.project("金额为零", info={"amount": "0"})
        self.project("未填金额")
        response, _ = self.listing()
        summary = self.data(response)["summary"]
        self.assertEqual((summary["amount"], summary["knownAmountCount"], summary["area"]), ("0.00", 1, None))
        for value in ("NaN", "Infinity", "-2", "1e100", True, "待定"):
            self.assertIsNone(_number(value))

    def test_sales_grouping_uses_ids_and_filters_apply_to_summary_and_details_together(self):
        project = self.project("目标项目", owner="first", name="同名销售")
        self.project("另一个项目", owner="second", name="同名销售")
        response, _ = self.listing(groupBy="sales")
        self.assertEqual(len(self.data(response)["groups"]), 2)
        response, _ = self.listing(groupBy="sales", search="目标", status="in_progress", groupKey="sales:first")
        payload = self.data(response)
        self.assertEqual(payload["summary"]["count"], 1)
        self.assertEqual([row["id"] for row in payload["items"]], [project.id])

    def test_denied_crm_scope_still_preserves_local_statistics(self):
        self.project("本地项目")
        self.project("CRM 项目", source="private", snapshot={"stage": "方案渗透"})
        request = self.request("get", "/api/after-sales/presales/statistics")
        with patch.object(views, "sync_crm_presales", side_effect=services.DomainValidationError(
            "CRM 无权访问", code="CRM_PERMISSION_DENIED", status=403,
        )):
            response = presales_statistics(request)
        payload = self.data(response)
        self.assertEqual(payload["summary"]["count"], 1)
        self.assertEqual(payload["items"][0]["name"], "本地项目")
        self.assertIn("CRM 无权访问", payload["crmSyncError"])

    def test_invalid_dimensions_or_status_and_non_management_users_are_rejected(self):
        for query in ({"groupBy": "arbitrary"}, {"status": "wrong"}):
            response, _ = self.listing(**query)
            self.assertEqual(response.status_code, 400)
        response, _ = self.listing(admin=False)
        self.assertEqual(response.status_code, 403)

    def test_crm_sync_retains_only_the_required_statistic_source_fields(self):
        from .test_crm_source import opportunity
        row = opportunity("statistics-source", amount="6.66", integrationWorkTypes=["家具"],
                          integrationEngineeringArea="10", bidTime="2026-11-20", secretComment="不应同步")
        project = crm_source._sync_row(self.request("post", "/"), row)
        self.assertEqual(project.crm_snapshot["amount"], "6.66")
        self.assertEqual(project.crm_snapshot["integrationWorkTypes"], ["家具"])
        self.assertEqual(project.crm_snapshot["bidTime"], "2026-11-20")
        self.assertNotIn("secretComment", project.crm_snapshot)

    def test_statistics_use_crm_original_creation_order_not_local_import_time(self):
        old = self.project("旧 CRM 项目", source="old", snapshot={"stage": "方案渗透", "createdAt": "2026-09-01T00:00:00Z"})
        new = self.project("新 CRM 项目", source="new", snapshot={"stage": "方案渗透", "createdAt": "2026-10-01T00:00:00Z"})
        ServiceProject.objects.filter(pk=old.pk).update(created_at=timezone.now())
        response, _ = self.listing(allowed=["old", "new"])
        self.assertEqual([row["id"] for row in self.data(response)["items"]], [new.id, old.id])

    def test_all_management_roles_can_read_but_wechat_and_unassigned_proxies_cannot(self):
        self.project("本地授权项目")
        for role in ("sales", "service", "admin"):
            user_id = f"statistics-{role}"
            AppPermissionRule.objects.create(permission=role, scope_type="employee", target_id=user_id)
            request = self.request("get", "/api/after-sales/presales/statistics", admin=False, user_id=user_id)
            with patch.object(views, "sync_crm_presales"):
                response = presales_statistics(request)
            self.assertEqual(response.status_code, 200, self.data(response))
        request = self.request("get", "/api/after-sales/presales/statistics", admin=True)
        request.auth_token_claims = {"chn": "wechat-mini"}
        self.assertEqual(presales_statistics(request).status_code, 403)
        request = self.request("get", "/api/after-sales/presales/statistics", admin=False, proxy=True, user_id="unassigned")
        self.assertEqual(presales_statistics(request).status_code, 403)

    def test_statistics_route_is_registered_and_does_not_allow_writes(self):
        from django.urls import resolve
        route = resolve("/api/after-sales/presales/statistics")
        self.assertEqual(route.func, presales_statistics)
        response = route.func(self.request("post", "/api/after-sales/presales/statistics"))
        self.assertEqual(response.status_code, 405)
