from copy import deepcopy
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.db import IntegrityError, connection, transaction
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from django.test.utils import CaptureQueriesContext

from . import approval_views, attachment_views, crm_source, services, views
from .models import AppPermissionRule, FieldFeedback, ProjectEvent, ProjectNode, Reward, ServiceProject, ServiceProvider, ServiceResource, ServiceTicket
from .presales_task_schedule import sync_presales_task_schedules
from .tests import CleanDomainMixin, RequestMixin


def opportunity(source_id="CRM-0007", **extra):
    return {
        "id": source_id, "name": "智慧教室项目", "customerName": "测试学校",
        "customerId": "customer-1", "ownerUserId": "crm-owner", "owner": "CRM 负责人",
        "overview": "建设智慧教室", "purchaseNeed": "设备及安装服务",
        "stage": "方案渗透", "status": "进行中", "orderType": "项目销售",
        "customerProvince": "浙江省", **extra,
    }


class CrmPresalesTests(RequestMixin, CleanDomainMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.clear_domain()
        cache.clear()
        self.addCleanup(cache.clear)

    def import_rows(self, rows):
        request = self.request("get", "/api/after-sales/projects", query={"type": "presales"})
        with patch.object(crm_source, "_request_payload", return_value={"items": rows}):
            with self.captureOnCommitCallbacks(execute=True):
                crm_source.sync_crm_presales(request, force=True)
            response = views.projects_collection(request)
        self.assertEqual(response.status_code, 200, self.data(response))
        return self.data(response)["items"]

    def test_import_immediately_creates_in_progress_workflow_with_crm_owner(self):
        items = self.import_rows([opportunity()])
        self.assertEqual(len(items), 1)
        item = items[0]
        project = ServiceProject.objects.get(pk=item["id"])
        self.assertEqual(project.status, "in_progress")
        self.assertEqual(project.current_node_key, "early-approval")
        self.assertEqual(project.owner_user_id, "crm-owner")
        self.assertEqual(project.owner_name, "CRM 负责人")
        self.assertEqual(project.created_by, "system-admin")
        self.assertEqual(project.business_data["projectInfo"]["owner"], "CRM 负责人")
        self.assertEqual(project.business_data["projectInfo"]["reason"], "")
        self.assertNotIn("managerContact", project.business_data)
        self.assertEqual(project.nodes.count(), len(services.PROJECT_NODE_TEMPLATES["presales"]))
        self.assertEqual(project.nodes.get(node_key="early-approval").status, "active")
        self.assertEqual(item["sourceCrmId"], "CRM-0007")
        self.assertEqual(item["crmStage"], "方案渗透")

    def test_automatic_import_and_viewing_do_not_create_manual_creation_history(self):
        project = ServiceProject.objects.get(pk=self.import_rows([opportunity()])[0]["id"])
        self.assertEqual(project.events.count(), 0)
        # Old CRM imports may already have a creation entry. Hide that entry,
        # retaining it in storage and retaining actual edits in the timeline.
        legacy = ProjectEvent.objects.create(project=project, event_type="project_created", title="创建服务项目")
        edited = ProjectEvent.objects.create(project=project, event_type="project_updated", title="更新项目资料")
        stamp = project.updated_at
        for _ in range(2):
            request = self.request("get", "/")
            with patch.object(crm_source, "_request_payload", return_value={"item": opportunity()}):
                response = views.project_item(request, project.pk)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual([event["id"] for event in self.data(response)["item"]["events"]], [edited.pk])
        project.refresh_from_db()
        self.assertEqual(project.updated_at, stamp)
        self.assertEqual(set(project.events.values_list("id", flat=True)), {legacy.pk, edited.pk})
        local = services.create_project(self.request("post", "/"), {
            "code": "manual-history", "name": "手工创建项目", "customer": "测试学校", "service_type": "presales",
        })
        response = views.project_item(self.request("get", "/"), local.pk)
        self.assertEqual([event["eventType"] for event in self.data(response)["item"]["events"]], ["project_created"])

    def test_node_selection_only_records_actual_changes_without_generic_update_events(self):
        project = services.create_project(self.request("post", "/"), {
            "code": "node-history", "name": "节点配置项目", "customer": "测试学校", "service_type": "presales",
        })
        original_stamp = project.updated_at
        for disabled, changed in (([], False), (["rendering"], True), (["rendering"], False)):
            project.refresh_from_db()
            stamp = project.updated_at
            response = views.project_item(self.request("patch", "/", {
                "disabledNodeKeys": disabled, "expectedUpdatedAt": project.updated_at.isoformat(),
            }), project.id)
            self.assertEqual(response.status_code, 200, response.content)
            project.refresh_from_db()
            self.assertEqual(project.updated_at != stamp, changed)
        self.assertEqual(project.events.filter(event_type="nodes_configured").count(), 1)
        self.assertEqual(project.events.filter(event_type="project_updated").count(), 0)
        stale = views.project_item(self.request("patch", "/", {
            "disabledNodeKeys": [], "expectedUpdatedAt": original_stamp.isoformat(),
        }), project.id)
        self.assertEqual(stale.status_code, 409, stale.content)
        self.assertFalse(project.nodes.get(node_key="rendering").enabled)
        invalid = views.project_item(self.request("patch", "/", {"disabledNodeKeys": ["unknown"]}), project.id)
        self.assertEqual(invalid.status_code, 400, invalid.content)
        self.assertEqual(project.events.count(), 2)

    def test_only_solution_penetration_and_later_sales_stages_create_presales(self):
        stages = ["在跟线索", "确认商机", "方案渗透", "标前准备", "挂网投标", "中标待签",
                  "待审合同", "已签合同", "采购预公告池", "采购结果池", "", None, "未知阶段"]
        rows = [opportunity(f"stage-{index}", stage=stage) for index, stage in enumerate(stages)]
        rows.append({key: value for key, value in opportunity("missing-stage").items() if key != "stage"})
        items = self.import_rows(rows)
        self.assertEqual({item["crmStage"] for item in items}, {
            "方案渗透", "标前准备", "挂网投标", "中标待签", "待审合同", "已签合同",
        })
        self.assertEqual(ServiceProject.objects.count(), 6)
        self.assertEqual(ProjectNode.objects.count(), 6 * len(services.PROJECT_NODE_TEMPLATES["presales"]))
        # The single-row initializer must enforce the same rule as bulk sync.
        self.assertIsNone(crm_source._sync_row(self.request("get", "/"), opportunity("direct-early", stage="确认商机")))
        self.assertFalse(ServiceProject.objects.filter(source_crm_id="direct-early").exists())

    def test_crm_creation_time_is_retained_separately_from_import_and_edits(self):
        row = opportunity(createdAt="2025-01-02T09:00:00+08:00")
        item = self.import_rows([row])[0]
        self.assertEqual(item["crmCreatedAt"], "2025-01-02T01:00:00+00:00")
        self.assertNotEqual(item["createdAt"], item["crmCreatedAt"])
        local_created_at = item["createdAt"]
        updated = self.import_rows([{**row, "name": "今天修改的旧商机"}])[0]
        self.assertEqual(updated["crmCreatedAt"], item["crmCreatedAt"])
        self.assertEqual(updated["createdAt"], local_created_at)

    def test_stage_promotion_imports_once_and_regression_preserves_existing_workflow(self):
        self.assertEqual(self.import_rows([opportunity(stage="确认商机")]), [])
        self.assertEqual(ServiceProject.objects.count(), 0)
        project = ServiceProject.objects.get(pk=self.import_rows([opportunity()])[0]["id"])
        node = project.nodes.get(node_key="early-plan")
        node.business_data = {"schemeRounds": [{"id": "retained-round", "note": "已有服务资料"}]}
        node.save()
        stamp = project.updated_at
        node_stamp = node.updated_at

        self.assertEqual(self.import_rows([opportunity(stage="在跟线索")]), [])
        project.refresh_from_db()
        node.refresh_from_db()
        self.assertEqual(project.crm_snapshot["stage"], "在跟线索")
        self.assertIsNone(project.deleted_at)
        self.assertEqual(project.status, "in_progress")
        self.assertEqual(project.updated_at, stamp)
        self.assertEqual(node.updated_at, node_stamp)
        self.assertEqual(node.business_data["schemeRounds"][0]["note"], "已有服务资料")

        items = self.import_rows([opportunity(stage="标前准备")])
        self.assertEqual([item["id"] for item in items], [project.pk])
        self.assertEqual(ServiceProject.objects.count(), 1)
        self.assertEqual(project.nodes.count(), len(services.PROJECT_NODE_TEMPLATES["presales"]))

    def test_repeat_sync_updates_basics_but_preserves_service_data_and_history(self):
        item = self.import_rows([opportunity()])[0]
        project = ServiceProject.objects.get(pk=item["id"])
        project.status = "completed"
        project.current_node_key = "project-end"
        project.business_data.update({
            "projectInfoRecords": {"early-approval": {"owner": "历史负责人", "files": ["原附件.pdf"]}},
            "applicationReason": "本地补充说明",
        })
        project.business_data["projectInfo"]["reason"] = "本地补充说明"
        project.save()
        stamp = project.updated_at
        node = project.nodes.get(node_key="early-plan")
        node.status = "completed"
        node.planned_start_at = timezone.now()
        node.business_data = {"schemeRounds": [{"id": "r1", "note": "历史方案"}]}
        node.save()
        history = list(project.events.values_list("id", flat=True))
        changed = opportunity(name="CRM 新名称", owner="新负责人", ownerUserId="owner-2", stage="已签合同")
        for _ in range(2):
            self.import_rows([changed])
        project.refresh_from_db()
        node.refresh_from_db()
        self.assertEqual(ServiceProject.objects.count(), 1)
        self.assertEqual(project.name, "CRM 新名称")
        self.assertEqual(project.owner_user_id, "owner-2")
        self.assertEqual(project.business_data["projectInfo"]["owner"], "新负责人")
        self.assertEqual(project.business_data["projectInfo"]["reason"], "本地补充说明")
        self.assertEqual(project.business_data["projectInfoRecords"]["early-approval"]["owner"], "历史负责人")
        self.assertEqual(project.status, "completed")
        self.assertEqual(project.current_node_key, "project-end")
        self.assertEqual(project.updated_at, stamp)
        self.assertEqual(node.status, "completed")
        self.assertEqual(node.business_data["schemeRounds"][0]["note"], "历史方案")
        self.assertIsNotNone(node.planned_start_at)
        self.assertEqual(list(project.events.values_list("id", flat=True)), history)

    def test_crm_completion_does_not_complete_service_and_same_name_does_not_merge(self):
        items = self.import_rows([opportunity("0007", status="已完成"), opportunity("7", orderType="产品销售")])
        self.assertEqual(len(items), 2)
        self.assertEqual({row["sourceCrmId"] for row in items}, {"0007", "7"})
        self.assertTrue(all(row["status"] == "in_progress" for row in items))

    def test_old_test_projects_are_listed_without_binding_and_remain_searchable(self):
        legacy = services.create_project(self.request("post", "/"), {
            "code": "legacy", "name": "智慧教室项目", "customer": "测试学校", "service_type": "presales",
        })
        items = self.import_rows([opportunity()])
        self.assertEqual(len(items), 2)
        self.assertEqual({item["sourceCrmId"] for item in items}, {"", "CRM-0007"})
        response = views.projects_collection(self.request("get", "/", query={
            "type": "presales", "customerSearch": "测试学校", "search": "智慧教室", "pageSize": 1,
        }))
        self.assertEqual(self.data(response)["total"], 2)
        self.assertEqual(self.data(response)["totalPages"], 2)
        legacy.refresh_from_db()
        self.assertEqual(legacy.source_crm_id, "")
        self.assertIsNone(legacy.deleted_at)

    def test_current_user_scope_hides_other_imports_without_deleting_them(self):
        self.import_rows([opportunity("a"), opportunity("b")])
        self.assertEqual([row["sourceCrmId"] for row in self.import_rows([opportunity("b")])], ["b"])
        self.assertEqual(ServiceProject.objects.count(), 2)
        self.assertEqual(self.import_rows([]), [])
        self.assertEqual(ServiceProject.objects.count(), 2)

    # Keep the mocked source failure inside this request rather than a background thread.
    @patch.object(crm_source, "_in_memory_database", return_value=True)
    def test_source_failure_is_reported_but_local_presales_remain_usable(self, _inline_sync):
        project_id = self.import_rows([opportunity()])[0]["id"]
        local = services.create_project(self.request("post", "/"), {
            "code": "local-only", "name": "本地测试", "customer": "测试学校", "service_type": "presales",
        })
        for failure in [crm_source.CrmSourceError(), crm_source.CrmSourceError("无权限", status=403, code="CRM_PERMISSION_DENIED")]:
            with self.subTest(code=failure.code), patch.object(crm_source, "_request_payload", side_effect=failure):
                response = views.projects_collection(self.request("get", "/", query={"type": "presales", "crmRefresh": "1"}))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.data(response)["crmSyncError"], str(failure))
                self.assertFalse(self.data(response)["crmScopeReady"])
                self.assertEqual([row["id"] for row in self.data(response)["items"]], [local.pk])
                detail = views.project_item(self.request("get", "/"), local.pk)
                self.assertEqual(detail.status_code, 200)
                edit = views.project_item(self.request("patch", "/", {"summary": "独立修改"}), local.pk)
                self.assertEqual(edit.status_code, 200)
        self.assertEqual(ServiceProject.objects.get(pk=project_id).status, "in_progress")

    def test_partial_or_invalid_list_never_imports_any_rows(self):
        payloads = [
            {"items": [opportunity()], "total": 2},
            {"items": [opportunity()], "hasNext": True},
            {"items": [opportunity(), {"id": ""}]},
            {"items": [opportunity(), {"id": "x" * 65}]},
        ]
        for payload in payloads:
            with self.subTest(payload=payload), patch.object(crm_source, "_request_payload", return_value=payload):
                response = views.projects_collection(self.request("get", "/", query={"type": "presales"}))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(self.data(response)["crmSyncError"])
                self.assertEqual(self.data(response)["items"], [])
        self.assertEqual(ServiceProject.objects.count(), 0)

    def test_deleted_crm_rows_do_not_import_or_restore_service_projects(self):
        project_id = self.import_rows([opportunity()])[0]["id"]
        ServiceProject.objects.filter(pk=project_id).update(deleted_at=timezone.now())
        self.assertEqual(self.import_rows([opportunity()]), [])
        self.assertIsNotNone(ServiceProject.objects.get(pk=project_id).deleted_at)
        self.assertEqual(self.import_rows([opportunity(deleted=True)]), [])
        self.assertEqual(ServiceProject.objects.count(), 1)

    def test_source_uniqueness_is_per_service_type(self):
        project = ServiceProject.objects.get(pk=self.import_rows([opportunity()])[0]["id"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            ServiceProject.objects.create(code="duplicate", service_type="presales", source_crm_id=project.source_crm_id)
        ServiceProject.objects.create(code="midsales-link", service_type="midsales", source_crm_id=project.source_crm_id)
        self.assertEqual(ServiceProject.objects.count(), 2)

    def test_manual_presales_create_edit_and_delete_never_bind_to_crm(self):
        payload = {"serviceType": "presales", "name": "独立售前项目", "customer": "本地客户",
                   "sourceCrmId": "must-not-bind", "source": "crm"}
        with patch.object(crm_source, "_request_payload", side_effect=AssertionError("local writes must not contact CRM")):
            response = views.projects_collection(self.request("post", "/", payload))
            self.assertEqual(response.status_code, 201, self.data(response))
            item = self.data(response)["item"]
            self.assertEqual(item["sourceCrmId"], "")
            project = ServiceProject.objects.get(pk=item["id"])
            self.assertEqual(project.nodes.count(), 19)
            self.assertEqual(project.owner_user_id, "system-admin")
            response = views.project_item(self.request("patch", "/", {"name": "本地改名"}), project.pk)
            self.assertEqual(response.status_code, 200)
            for proxy in (False, True):
                request = self.request("delete", "/", admin=False, user_id="ordinary-user", proxy=proxy)
                request.auth_token_claims = {"chn": "wechat-mini", "aud": "after-sales-mobile"}
                self.assertEqual(views.project_item(request, project.pk).status_code, 403)
            response = views.project_item(self.request("delete", "/"), project.pk)
            self.assertEqual(response.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.source_crm_id, "")
        self.assertIsNotNone(project.deleted_at)
        self.assertEqual(project.nodes.count(), 19)

    def test_crm_delete_is_rejected_even_with_source_access_or_an_unavailable_source(self):
        project = ServiceProject.objects.get(pk=self.import_rows([opportunity()])[0]["id"])
        before = (project.updated_at, project.nodes.count(), project.events.count())
        with patch.object(crm_source, "_request_payload", side_effect=AssertionError("deletion must reject without fetching CRM")):
            for proxy in (False, True):
                response = views.project_item(self.request("delete", "/", proxy=proxy), project.pk)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.data(response)["code"], "CRM_PROJECT_DELETE_FORBIDDEN")
        project.refresh_from_db()
        self.assertIsNone(project.deleted_at)
        self.assertEqual((project.updated_at, project.nodes.count(), project.events.count()), before)

    def test_manual_projects_remain_visible_to_app_admin_without_crm_permission(self):
        self.import_rows([opportunity()])
        local = services.create_project(self.request("post", "/"), {
            "code": "local-admin", "name": "本地权限测试", "customer": "测试客户", "service_type": "presales",
        })
        AppPermissionRule.objects.create(permission="admin", scope_type="employee", target_id="service-admin")
        with patch.object(crm_source, "_request_payload", side_effect=crm_source.CrmSourceError("CRM 无权限", status=403, code="CRM_PERMISSION_DENIED")):
            for proxy in (False, True):
                response = views.projects_collection(self.request("get", "/", user_id="service-admin", admin=False, proxy=proxy,
                                                                   query={"type": "presales"}))
                self.assertEqual(response.status_code, 200)
                self.assertEqual([row["id"] for row in self.data(response)["items"]], [local.pk])
                self.assertEqual(self.data(response)["crmSyncError"], "CRM 无权限")
            request = self.request("get", "/", user_id="ordinary-user", admin=False, query={"type": "presales"})
            request.auth_token_claims = {"chn": "wechat-mini", "aud": "after-sales-mobile"}
            denied = views.projects_collection(request)
            self.assertEqual(denied.status_code, 403)

    def test_detail_refreshes_crm_basics_and_local_reason_can_be_empty(self):
        project_id = self.import_rows([opportunity()])[0]["id"]
        with patch.object(crm_source, "_request_payload", return_value={"item": opportunity(owner="更新负责人")}):
            response = views.project_item(self.request("get", "/"), project_id)
            self.assertEqual(self.data(response)["item"]["ownerName"], "更新负责人")
            response = views.project_item(self.request("patch", "/", {"businessData": {
                "applicationReason": "", "projectInfo": {"reason": "", "owner": "试图覆盖"},
            }}), project_id)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertEqual(self.data(response)["item"]["businessData"]["projectInfo"]["owner"], "更新负责人")
        self.assertEqual(self.data(response)["item"]["businessData"]["applicationReason"], "")
        with patch.object(crm_source, "_request_payload", return_value={"item": opportunity()}):
            response = views.project_item(self.request("patch", "/", {"ownerName": "本地负责人"}), project_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.data(response)["code"], "CRM_FIELDS_READ_ONLY")

    def test_crm_permission_denial_blocks_detail_mutation_approval_and_attachment(self):
        project = ServiceProject.objects.get(pk=self.import_rows([opportunity()])[0]["id"])
        node = project.nodes.get(node_key="early-approval")
        original_node_data = deepcopy(node.business_data)
        denied = crm_source.CrmSourceError("无权读取", status=403, code="CRM_PERMISSION_DENIED")
        with patch.object(crm_source, "_request_payload", side_effect=denied):
            calls = [
                lambda: views.project_item(self.request("get", "/"), project.id),
                lambda: views.project_item(self.request("patch", "/", {"summary": "覆盖"}), project.id),
                lambda: views.project_item(self.request("delete", "/"), project.id),
                lambda: views.project_restore(self.request("post", "/"), project.id),
                lambda: views.project_start(self.request("post", "/", {"nodeKey": node.node_key}), project.id),
                lambda: views.project_node_autosave(self.request("patch", "/", {"businessData": {"note": "覆盖"}}), project.id, node.node_key),
                lambda: approval_views.presales_approvals(self.request("get", "/"), project.id, node.node_key),
            ]
            for call in calls:
                self.assertEqual(call().status_code, 403)
            target, allowed, failure = attachment_views._target_access(self.request("get", "/"), "project_node", node.id)
            self.assertIsNone(target)
            self.assertFalse(allowed)
            self.assertEqual(failure.status_code, 403)
        project.refresh_from_db()
        node.refresh_from_db()
        self.assertIsNone(project.deleted_at)
        self.assertEqual(node.business_data, original_node_data)

    def test_app_admin_and_proxy_still_use_effective_crm_user(self):
        project_id = self.import_rows([opportunity()])[0]["id"]
        AppPermissionRule.objects.create(permission="admin", scope_type="employee", target_id="service-admin")
        for proxy in [False, True]:
            request = self.request("get", "/", user_id="service-admin", admin=False, proxy=proxy)
            request.COOKIES["mj_auth_token"] = "effective-user-session"
            with patch.object(crm_source, "_request_payload", side_effect=crm_source.CrmSourceError(status=403)):
                response = views.project_item(request, project_id)
            self.assertEqual(response.status_code, 403)

    def test_related_lists_do_not_expose_other_crm_projects(self):
        self.import_rows([opportunity("visible"), opportunity("hidden")])
        for project in ServiceProject.objects.all():
            ServiceResource.objects.create(title=project.source_crm_id, project=project, resource_type="document", audience="assigned")
        cache.clear()
        with patch.object(crm_source, "_request_payload", return_value={"items": [opportunity("visible")]}):
            response = views.resources_collection(self.request("get", "/"))
        self.assertEqual([row["title"] for row in self.data(response)["items"]], ["visible"])

    def test_midsales_and_aftersales_lists_do_not_depend_on_crm(self):
        self.import_rows([opportunity()])
        with patch.object(crm_source, "_request_payload", side_effect=AssertionError("must not contact CRM")):
            for service_type in ["midsales", "aftersales"]:
                response = views.projects_collection(self.request("get", "/", query={"type": service_type}))
                self.assertEqual(response.status_code, 200)


@override_settings(CRM_PROJECT_SOURCE={"BASE_URL": "http://crm-backend:8000/api/crm/", "TIMEOUT_SECONDS": 2})
class CrmClientTests(TestCase):
    def test_invalid_or_missing_crm_creation_time_never_uses_import_time(self):
        for value in (None, "", "invalid", "2026-13-45T08:00:00Z", {}):
            with self.subTest(value=value):
                self.assertNotIn("createdAt", crm_source._source_row(opportunity(createdAt=value)))
        self.assertEqual(crm_source._source_row(opportunity(createdAt="2026-10-16T08:00:00"))["createdAt"],
                         "2026-10-16T00:00:00+00:00")

    def test_connection_reset_retries_only_the_failed_get_with_same_identity(self):
        request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer same-user")
        with patch.object(crm_source, "sleep"), patch.object(crm_source, "urlopen", side_effect=[
            ConnectionResetError("CRM restarted"), URLError("reconnecting"), BytesIO(b'{"items":[]}'),
        ]) as client:
            self.assertEqual(crm_source.crm_opportunities(request), [])
        self.assertEqual(client.call_count, 3)
        self.assertEqual(len({call.args[0].full_url for call in client.call_args_list}), 1)
        self.assertTrue(all(call.args[0].get_header("Authorization") == "Bearer same-user" for call in client.call_args_list))

    def test_denied_or_malformed_response_is_not_retried_and_denial_clears_scope(self):
        request = RequestFactory().get("/")
        cache.clear()
        self.addCleanup(cache.clear)
        for failure in (HTTPError("/", 403, "denied", {}, None), BytesIO(b'not-json')):
            cache.clear()
            crm_source._remember_scope(request, ["old-project"], synced=True)
            with patch.object(crm_source, "urlopen", side_effect=[failure]) as client:
                with self.assertRaises(crm_source.CrmSourceError):
                    crm_source.crm_opportunities(request)
            self.assertEqual(client.call_count, 1)
            if isinstance(failure, HTTPError):
                self.assertIsNone(cache.get(crm_source._cache_key(request)))
                crm_source._remember_error(request, crm_source.CrmSourceError())
                with self.assertRaises(crm_source.CrmSourceError) as denied:
                    crm_source.crm_visible_ids(request)
                self.assertEqual(denied.exception.code, "CRM_PERMISSION_DENIED")

    def test_forwards_current_session_cookie_and_authorization(self):
        request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer current-token")
        request.COOKIES.update({"mj_auth_token": "current-session", "unrelated": "private"})
        with patch.object(crm_source, "urlopen", return_value=BytesIO(b'{"items":[]}')) as client:
            self.assertEqual(crm_source.crm_opportunities(request), [])
        outbound = client.call_args.args[0]
        self.assertEqual(outbound.get_header("Cookie"), "mj_auth_token=current-session")
        self.assertEqual(outbound.get_header("Authorization"), "Bearer current-token")
        self.assertEqual(outbound.full_url, "http://crm-backend:8000/api/crm/opportunities")
        self.assertEqual(client.call_args.kwargs["timeout"], 2)

    def test_source_errors_distinguish_permissions_missing_project_and_network(self):
        cases = [(HTTPError("/", 401, "expired", {}, None), 401), (HTTPError("/", 403, "denied", {}, None), 403),
                 (HTTPError("/", 404, "missing", {}, None), 404), (URLError("offline"), 503)]
        for failure, expected in cases:
            with self.subTest(expected=expected), patch.object(crm_source, "urlopen", side_effect=failure):
                with self.assertRaises(crm_source.CrmSourceError) as caught:
                    crm_source.crm_opportunities(RequestFactory().get("/"))
                self.assertEqual(caught.exception.status, expected)

    def test_large_source_uses_one_cached_crm_response_and_keeps_only_service_fields(self):
        rows = [opportunity(f"crm-{index}", internalIgnored="not needed") for index in range(1507)]
        request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer source-user")
        with patch.object(crm_source, "_request_payload", return_value={"items": rows, "cacheHit": True}) as client:
            result = crm_source.crm_opportunities(request)
            self.assertEqual(crm_source.crm_opportunities(request), result)
        self.assertEqual(len(result), 1507)
        self.assertEqual([row["id"] for row in result], [row["id"] for row in rows])
        self.assertNotIn("internalIgnored", result[0])
        client.assert_called_once_with(request, "opportunities")

    def test_source_failure_never_imports_or_renews_existing_scope(self):
        cache.clear()
        self.addCleanup(cache.clear)
        for failure in [crm_source.CrmSourceError(), crm_source.CrmSourceError("CRM 无权限", status=403, code="CRM_PERMISSION_DENIED")]:
            cache.clear()
            request = RequestFactory().get("/")
            crm_source._remember_scope(request, ["previously-visible"], synced=True)
            before = cache.get(crm_source._cache_key(request))
            with self.subTest(code=failure.code), \
                    patch.object(crm_source, "_request_payload", side_effect=failure), \
                    patch.object(crm_source, "_sync_rows") as sync:
                with self.assertRaises(crm_source.CrmSourceError):
                    crm_source.sync_crm_presales(request, force=True)
            sync.assert_not_called()
            self.assertFalse(hasattr(request, "_after_sales_crm_rows"))
            key = crm_source._cache_key(request)
            self.assertEqual(cache.get(key), None if failure.status == 403 else before)
            if failure.status == 403:
                self.assertIsNone(cache.get(key + ":fresh"))

    def test_truncated_duplicate_or_invalid_snapshots_never_publish_visibility(self):
        rows = [opportunity("crm-1"), opportunity("crm-2")]
        cases = [
            {"items": rows[:1], "total": 2},
            {"items": rows, "page": 1, "pageSize": 2, "totalPages": 1},
            {"items": rows, "hasNext": True},
            {"items": [rows[0], rows[0]]},
            {"items": rows, "total": "2"},
            {"items": None},
            {"items": [*rows, {"id": ""}]},
            {"items": [*rows, None]},
        ]
        cache.clear()
        self.addCleanup(cache.clear)
        for payload in cases:
            request = RequestFactory().get("/")
            crm_source._remember_scope(request, ["previously-visible"], synced=True)
            before = cache.get(crm_source._cache_key(request))
            with self.subTest(payload=payload), patch.object(crm_source, "_request_payload", return_value=payload), \
                    patch.object(crm_source, "_sync_rows") as sync:
                with self.assertRaises(crm_source.CrmSourceError):
                    crm_source.sync_crm_presales(request, force=True)
                sync.assert_not_called()
                self.assertFalse(hasattr(request, "_after_sales_crm_rows"))
                self.assertEqual(cache.get(crm_source._cache_key(request)), before)

    def test_complete_source_including_empty_and_deleted_rows(self):
        for count in (0, 100, 200):
            rows = [opportunity(f"crm-{index}") for index in range(count)]
            with self.subTest(count=count), patch.object(crm_source, "_request_payload", return_value={"items": rows}) as client:
                self.assertEqual(len(crm_source.crm_opportunities(RequestFactory().get("/"))), count)
                self.assertEqual(client.call_count, 1)
        with patch.object(crm_source, "_request_payload", return_value={"items": [opportunity(deleted=True)]}):
            self.assertEqual(crm_source.crm_opportunities(RequestFactory().get("/")), [])


class CrmPaginationTests(RequestMixin, CleanDomainMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.clear_domain()
        cache.clear()
        self.addCleanup(cache.clear)

    def seed_scope(self, count=1500, *, full_nodes=False):
        rows = [opportunity(f"crm-{index}", name=f"普通项目 {index}") for index in range(count)]
        projects = ServiceProject.objects.bulk_create([
            ServiceProject(code=f"page-{index}", service_type="presales", source_crm_id=row["id"],
                           status="in_progress", current_node_key="early-approval", crm_snapshot=row,
                           **crm_source._source_fields(row))
            for index, row in enumerate(rows)
        ])
        template = services.PROJECT_NODE_TEMPLATES["presales"] if full_nodes else [services.PROJECT_NODE_TEMPLATES["presales"][0]]
        ProjectNode.objects.bulk_create([
            ProjectNode(project=item, node_key=key, name=name, kind=kind, sequence=sequence,
                        status="active" if sequence == 1 else "pending", planned_end_at=timezone.now())
            for item in projects for sequence, (key, name, kind, _description) in enumerate(template, start=1)
        ], batch_size=500)
        crm_source._remember_scope(self.request("get", "/"), [row["id"] for row in rows], synced=True)
        return rows, projects

    def test_large_cached_list_returns_only_requested_page_with_bounded_queries(self):
        self.seed_scope(full_nodes=True)
        request = self.request("get", "/", query={"type": "presales", "page": 37, "pageSize": 20})
        with patch.object(crm_source, "_request_payload", side_effect=AssertionError("warm page must not fetch CRM")), \
                patch.object(crm_source, "_sync_rows", side_effect=AssertionError("warm page must not import")), \
                CaptureQueriesContext(connection) as queries:
            response = views.projects_collection(request)
        payload = self.data(response)
        self.assertEqual(response.status_code, 200, payload)
        self.assertEqual((payload["total"], payload["totalPages"], payload["page"]), (1500, 75, 37))
        self.assertEqual(len(payload["items"]), 20)
        self.assertLessEqual(len(queries), 5)  # One distinct-label query for the stage filter.
        self.assertEqual(payload["crmStageOptions"], ["方案渗透"])
        self.assertNotIn("nodes", payload["items"][0])
        self.assertEqual(payload["items"][0]["plannedEndDate"], "", "legacy node dates are not task deadlines")

    def test_stage_gate_hides_legacy_imports_before_pagination_dashboard_and_related_lists(self):
        rows, projects = self.seed_scope(8)
        for project, snapshot in zip(projects[:5], (
            {"stage": "在跟线索"}, {"stage": "确认商机"}, {}, {"stage": None}, {"stage": "采购结果池"},
        )):
            ServiceProject.objects.filter(pk=project.pk).update(crm_snapshot=snapshot, status="blocked")
            project.nodes.update(business_data={"managementAssignment": {"userId": "system-admin"}})
        ServiceProject.objects.filter(pk=projects[6].pk).update(crm_snapshot={"stage": "已签合同"})
        crm_source._remember_scope(self.request("get", "/"), [row["id"] for row in rows[:7]], synced=True)
        local = services.create_project(self.request("post", "/"), {
            "code": "local-stage-gate", "name": "本地售前", "customer": "学校", "service_type": "presales",
        })
        midsales = services.create_project(self.request("post", "/"), {
            "code": "midsales-stage-gate", "name": "独立售中", "customer": "学校", "service_type": "midsales",
            "source_crm_id": rows[0]["id"], "crm_snapshot": {"stage": "在跟线索"},
        })
        for project in projects:
            ServiceResource.objects.create(title=project.source_crm_id, project=project, resource_type="document", audience="assigned")

        with patch.object(crm_source, "_request_payload", side_effect=AssertionError("warm scope must not fetch CRM")):
            payload = self.data(views.projects_collection(self.request("get", "/", query={
                "type": "presales", "pageSize": 1,
            })))
            self.assertEqual((payload["total"], payload["totalPages"]), (3, 3))
            self.assertEqual(set(payload["crmStageOptions"]), {"方案渗透", "已签合同"})
            for stage in ("在跟线索", "确认商机"):
                filtered = self.data(views.projects_collection(self.request("get", "/", query={
                    "type": "presales", "crmStage": stage,
                })))
                self.assertEqual(filtered["total"], 0)
            dashboard = self.data(views.dashboard(self.request("get", "/")))
            self.assertEqual(dashboard["metrics"]["projects"], 4)
            self.assertEqual({item["id"] for item in dashboard["recentProjects"]}, {
                projects[5].pk, projects[6].pk, local.pk, midsales.pk,
            })
            self.assertEqual(dashboard["taskTotal"], 0)
            self.assertEqual(dashboard["alertTotal"], 0)
            resources = self.data(views.resources_collection(self.request("get", "/")))
            self.assertEqual({item["projectId"] for item in resources["items"]}, {projects[5].pk, projects[6].pk})
        self.assertEqual(ServiceProject.objects.count(), 10, "hidden service records must be retained")

    def test_filters_search_all_rows_and_counts_and_out_of_range_pages_are_correct(self):
        _, projects = self.seed_scope(125)
        target = projects[0]
        ServiceProject.objects.filter(pk=target.pk).update(
            name="特殊智慧校园", customer="独立实验学校", owner_name="指定王经理",
            status="completed", current_node_key="project-end", crm_snapshot={"stage": "已签合同"},
        )
        cases = [{"search": "特殊智慧校园"}, {"customerSearch": "独立实验学校"},
                 {"ownerSearch": "指定王经理"}, {"nodeKey": "project-end"},
                 {"completion": "completed"}, {"nodeKey": "completed", "completion": "completed"},
                 {"crmStage": "已签合同"}, {"crmStage": "已签合同", "ownerSearch": "指定王经理"}]
        for filters in cases:
            with self.subTest(filters=filters):
                response = views.projects_collection(self.request("get", "/", query={
                    "type": "presales", "pageSize": 20, "page": 99, **filters,
                }))
                payload = self.data(response)
                self.assertEqual((payload["page"], payload["total"]), (1, 1))
                self.assertEqual(payload["items"][0]["id"], target.pk)
                self.assertEqual(payload["crmStageOptions"], ["方案渗透", "已签合同"])
        response = views.projects_collection(self.request("get", "/", query={"type": "presales", "completion": "active"}))
        self.assertEqual(self.data(response)["total"], 124)

    def test_name_search_ranks_exact_prefix_and_contains_before_pagination(self):
        _, projects = self.seed_scope(35)
        ServiceProject.objects.update(name="名称包含13的CRM项目", customer="客户13", owner_name="负责人13", address="13号地址")
        now = timezone.now()
        ServiceProject.objects.filter(pk=projects[0].pk).update(name="13", updated_at=now - timedelta(days=10),
            crm_snapshot={**projects[0].crm_snapshot, "createdAt": (now - timedelta(days=10)).isoformat()})
        ServiceProject.objects.filter(pk=projects[1].pk).update(name="13号项目", updated_at=now - timedelta(days=5),
            crm_snapshot={**projects[1].crm_snapshot, "createdAt": (now - timedelta(days=5)).isoformat()})
        # Matching codes, customers, owners and addresses must not add a name-search result.
        ServiceProject.objects.filter(pk=projects[-1].pk).update(name="无关项目", code="PS-20260913-hidden")
        local = services.create_project(self.request("post", "/"), {
            "code": "old-local-exact", "name": "13", "customer": "本地学校", "service_type": "presales",
        })
        ServiceProject.objects.filter(pk=local.pk).update(created_at=now - timedelta(days=20), updated_at=now)

        query = {"type": "presales", "nameSearch": " 13 ", "pageSize": 2}
        with patch.object(views, "filter_queryset_search", side_effect=AssertionError("name search must stay in SQL")), \
                CaptureQueriesContext(connection) as queries:
            payload = self.data(views.projects_collection(self.request("get", "/", query=query)))
        self.assertEqual((payload["total"], payload["totalPages"]), (35, 18))
        self.assertEqual([item["id"] for item in payload["items"]], [projects[0].pk, local.pk])
        self.assertLessEqual(len(queries), 5)
        second = self.data(views.projects_collection(self.request("get", "/", query={**query, "page": 2})))
        self.assertEqual(second["items"][0]["id"], projects[1].pk)
        self.assertTrue(all("13" in item["name"] for item in second["items"]))

        unfiltered = self.data(views.projects_collection(self.request("get", "/", query={"type": "presales", "pageSize": 2})))
        self.assertEqual([item["id"] for item in unfiltered["items"]], [projects[1].pk, projects[0].pk])
        self.assertEqual(unfiltered["total"], 36)

    def test_source_creation_orders_all_pages_and_overview_without_refetching_crm(self):
        _, projects = self.seed_scope(4)
        now = timezone.now()
        for index, age in enumerate((0, 10, 0)):
            ServiceProject.objects.filter(pk=projects[index].pk).update(
                crm_snapshot={**projects[index].crm_snapshot, "createdAt": (now - timedelta(days=age)).isoformat()},
                # Deliberately reverse local import/edit times relative to CRM creation.
                created_at=now - timedelta(days=20 - index), updated_at=now + timedelta(days=index),
            )
        local = services.create_project(self.request("post", "/"), {
            "code": "local-recency", "name": "本地项目", "customer": "学校", "service_type": "presales",
        })
        ServiceProject.objects.filter(pk=local.pk).update(created_at=now - timedelta(days=1))
        expected = [projects[2].pk, projects[0].pk, local.pk, projects[1].pk, projects[3].pk]
        actual = []
        with patch.object(crm_source, "_request_payload", side_effect=AssertionError("sorting must not fetch CRM")):
            for page in (1, 2, 3):
                payload = self.data(views.projects_collection(self.request("get", "/", query={
                    "type": "presales", "page": page, "pageSize": 2,
                })))
                actual.extend(item["id"] for item in payload["items"])
                self.assertEqual(payload["total"], 5)
            dashboard = self.data(views.dashboard(self.request("get", "/")))
        self.assertEqual(actual, expected)
        self.assertEqual([item["id"] for item in dashboard["recentProjects"]], expected)
        source_dates = {item["id"]: item["crmCreatedAt"] for item in dashboard["recentProjects"]}
        self.assertEqual(source_dates[projects[0].pk], now.isoformat())
        self.assertEqual(source_dates[local.pk], "")
        self.assertEqual(source_dates[projects[3].pk], "")

    def test_name_search_preserves_authorization_and_intersects_other_filters(self):
        rows, projects = self.seed_scope(4)
        ServiceProject.objects.filter(pk__in=[item.pk for item in projects]).update(name="13", customer="另一客户")
        ServiceProject.objects.filter(pk=projects[0].pk).update(name="13号项目", customer="指定客户")
        ServiceProject.objects.filter(pk=projects[2].pk).update(deleted_at=timezone.now())
        crm_source._remember_scope(self.request("get", "/"), [row["id"] for row in rows[:3]], synced=True)
        payload = self.data(views.projects_collection(self.request("get", "/", query={"type": "presales", "nameSearch": "13"})))
        self.assertEqual([item["id"] for item in payload["items"]], [projects[1].pk, projects[0].pk])
        payload = self.data(views.projects_collection(self.request("get", "/", query={
            "type": "presales", "nameSearch": "13", "customerSearch": "指定客户", "crmStage": "方案渗透",
        })))
        self.assertEqual([item["id"] for item in payload["items"]], [projects[0].pk])
        payload = self.data(views.projects_collection(self.request("get", "/", query={
            "type": "presales", "nameSearch": "13", "customerSearch": "不存在的客户",
        })))
        self.assertEqual(payload["total"], 0)

    def test_name_search_is_case_insensitive_and_midsales_uses_the_same_ranking(self):
        for index, name in enumerate(["LAB13", "lab13安装项目", "校内Lab13项目"]):
            services.create_project(self.request("post", "/"), {
                "code": f"midsales-name-{index}", "name": name, "customer": "学校", "service_type": "midsales",
            })
        payload = self.data(views.projects_collection(self.request("get", "/", query={"type": "midsales", "nameSearch": "lab13"})))
        self.assertEqual([item["name"] for item in payload["items"]], ["LAB13", "lab13安装项目", "校内Lab13项目"])

    def test_crm_stage_filter_handles_empty_values_and_scopes_options(self):
        rows, projects = self.seed_scope(6)
        ServiceProject.objects.filter(pk=projects[0].pk).update(crm_snapshot={"stage": "已签合同"})
        for project, snapshot in zip(projects[1:4], ({}, {"stage": None}, {"stage": ""})):
            ServiceProject.objects.filter(pk=project.pk).update(crm_snapshot=snapshot)
        ServiceProject.objects.filter(pk=projects[5].pk).update(crm_snapshot={"stage": "不可见阶段"})
        crm_source._remember_scope(self.request("get", "/"), [row["id"] for row in rows[:5]], synced=True)
        local = services.create_project(self.request("post", "/"), {
            "code": "local-stage", "name": "本地项目", "customer": "学校", "service_type": "presales",
        })
        # A local project's legacy snapshot does not make it a CRM project.
        ServiceProject.objects.filter(pk=local.pk).update(crm_snapshot={"stage": "已签合同"})
        payload = self.data(views.projects_collection(self.request("get", "/", query={
            "type": "presales", "crmStage": "__empty__", "pageSize": 1,
        })))
        self.assertEqual((payload["total"], payload["totalPages"]), (1, 1))
        self.assertEqual(payload["items"][0]["id"], local.pk)
        self.assertEqual(set(payload["crmStageOptions"]), {"方案渗透", "已签合同"})
        payload = self.data(views.projects_collection(self.request("get", "/", query={
            "type": "presales", "crmStage": "已签合同",
        })))
        self.assertEqual([item["id"] for item in payload["items"]], [projects[0].pk])
        payload = self.data(views.projects_collection(self.request("get", "/", query={
            "type": "presales", "crmStage": "不可见阶段",
        })))
        self.assertEqual(payload["total"], 0)
        self.assertNotIn("不可见阶段", payload["crmStageOptions"])

    def test_first_load_is_nonblocking_and_concurrent_requests_share_one_sync(self):
        # Locally imported rows must not leak into a new user's first snapshot.
        self.seed_scope(2)
        local = services.create_project(self.request("post", "/"), {
            "code": "local-during-sync", "name": "本地项目", "customer": "学校", "service_type": "presales",
        })
        with patch.object(crm_source, "_in_memory_database", return_value=False), \
                patch.object(crm_source.threading, "Thread") as thread, \
                patch.object(crm_source, "_request_payload", side_effect=AssertionError("HTTP request must not wait for CRM")):
            for page in (1, 2, 1):
                request = self.request("get", "/", user_id="another-user", query={"type": "presales", "page": page})
                response = views.projects_collection(request)
                payload = self.data(response)
                self.assertEqual(response.status_code, 200, payload)
                self.assertEqual([row["id"] for row in payload["items"]], [local.pk])
                self.assertTrue(payload["crmSyncing"])
        thread.assert_called_once()
        thread.return_value.start.assert_called_once()

    def test_local_and_crm_share_pagination_without_exposing_out_of_scope_crm(self):
        rows, projects = self.seed_scope(25)
        local = services.create_project(self.request("post", "/"), {
            "code": "local-mixed", "name": "本地历史项目", "customer": "本地客户", "service_type": "presales",
        })
        ids = []
        for page in (1, 2):
            payload = self.data(views.projects_collection(self.request("get", "/", query={
                "type": "presales", "page": page, "pageSize": 20,
            })))
            self.assertEqual((payload["total"], payload["totalPages"]), (26, 2))
            ids.extend(item["id"] for item in payload["items"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {local.pk, *(project.pk for project in projects)})
        # Local visibility does not widen the CRM session's source scope.
        crm_source._remember_scope(self.request("get", "/"), [rows[0]["id"]], synced=True)
        payload = self.data(views.projects_collection(self.request("get", "/", query={"type": "presales"})))
        self.assertEqual(payload["total"], 2)
        self.assertEqual({item["id"] for item in payload["items"]}, {local.pk, projects[0].pk})
        payload = self.data(views.projects_collection(self.request("get", "/", query={
            "type": "presales", "search": "本地历史", "customerSearch": "本地客户",
        })))
        self.assertEqual([item["id"] for item in payload["items"]], [local.pk])

    def test_verified_crm_scope_shows_existing_projects_before_workflow_import_finishes(self):
        rows, projects = self.seed_scope(3)
        ServiceProject.objects.all().update(created_by="system-admin")
        rows[1]["name"] = "唯一检索验证"
        ServiceProject.objects.filter(pk=projects[1].pk).update(name=rows[1]["name"])
        request = self.request("get", "/")
        cache.clear()
        # Only two of the three local CRM projects remain source-visible.
        visible_rows = rows[:2]
        cache.set(crm_source._cache_key(request) + ":lock", "import-in-progress", timeout=90)

        def importing(copied, source_rows):
            # Observe both screens while the background importer is pending.
            with patch.object(crm_source, "_in_memory_database", return_value=False):
                payload = self.data(views.projects_collection(self.request("get", "/", query={"type": "presales"})))
                overview = self.data(views.dashboard(self.request("get", "/")))
            self.assertEqual({item["id"] for item in payload["items"]}, {project.pk for project in projects[:2]})
            self.assertEqual(overview["metrics"]["projects"], 2)
            self.assertTrue(payload["crmScopeReady"])
            self.assertTrue(payload["crmSyncing"])
            self.assertEqual(payload["crmSyncedAt"], "")
            return [row["id"] for row in source_rows]

        with patch.object(crm_source, "_request_payload", return_value={"items": visible_rows, "cacheHit": True}) as source, \
                patch.object(crm_source, "_sync_rows", side_effect=importing):
            with self.captureOnCommitCallbacks(execute=True):
                crm_source.sync_crm_presales(request, force=True)
        source.assert_called_once()
        # A re-login also has the same full server-side search/pagination scope.
        again = self.request("get", "/", query={"type": "presales", "search": "唯一检索验证"})
        again.auth_introspection = {"sessionId": "new-login"}
        with patch.object(crm_source, "_request_payload", side_effect=AssertionError("must reuse verified scope")):
            payload = self.data(views.projects_collection(again))
        self.assertEqual([item["id"] for item in payload["items"]], [projects[1].pk])

    def test_snapshot_keeps_one_refresh_window_without_import_extending_authorization(self):
        request = self.request("get", "/")
        verified_at = timezone.now()
        with patch.object(crm_source.timezone, "now", return_value=verified_at + timedelta(seconds=200)):
            crm_source._remember_scope(request, ["visible"], synced=True, verified_at=verified_at)
        snapshot = cache.get(crm_source._cache_key(request))
        self.assertEqual(snapshot["expiresAt"], (verified_at + timedelta(seconds=600)).isoformat())
        self.assertEqual(snapshot["verifiedAt"], verified_at.isoformat())

    def test_old_login_expiry_does_not_revoke_the_same_users_verified_snapshot(self):
        self.seed_scope(2)
        request = self.request("get", "/")
        key = crm_source._cache_key(request)
        previous = cache.get(key)
        with patch.object(crm_source, "urlopen", side_effect=HTTPError("/", 401, "expired", {}, None)) as source:
            with self.assertRaises(crm_source.CrmSourceError) as failure:
                crm_source.sync_crm_presales(request, force=True)
        self.assertEqual(failure.exception.code, "CRM_SESSION_EXPIRED")
        self.assertEqual(source.call_count, 1)
        self.assertEqual(cache.get(key), previous)
        self.assertIsNone(cache.get(key + ":error"))

    def test_permission_revoked_during_import_cannot_be_overwritten_by_completion(self):
        rows, _projects = self.seed_scope(2)
        request = self.request("get", "/")
        denied = crm_source.CrmSourceError("CRM 无权限", status=403, code="CRM_PERMISSION_DENIED")

        def importing(copied, source_rows):
            crm_source._remember_error(copied, denied)
            # The short error has expired, but the importer is still working.
            cache.delete(crm_source._cache_key(copied) + ":error")
            return [row["id"] for row in source_rows]

        with patch.object(crm_source, "_request_payload", return_value={"items": rows}), \
                patch.object(crm_source, "_sync_rows", side_effect=importing):
            with self.assertRaises(crm_source.CrmSourceError) as failure:
                with self.captureOnCommitCallbacks(execute=True):
                    crm_source.sync_crm_presales(request, force=True)
        self.assertEqual(failure.exception.code, "CRM_PERMISSION_DENIED")
        key = crm_source._cache_key(request)
        self.assertIsNone(cache.get(key))
        self.assertIsNone(cache.get(key + ":fresh"))

    def test_relogin_reuses_same_user_scope_but_other_users_actors_and_capabilities_are_isolated(self):
        original = self.request("get", "/")
        original.auth_introspection = {"sessionId": "sid-1"}
        original.COOKIES["mj_auth_token"] = "old-token"
        crm_source._remember_scope(original, ["only-mine"], synced=True)
        same = self.request("get", "/")
        same.auth_introspection = {"sessionId": "sid-2"}
        same.COOKIES["mj_auth_token"] = "renewed-token"
        with patch.object(crm_source, "_request_payload", side_effect=AssertionError("re-login must reuse the same user's scope")):
            self.assertEqual(crm_source.crm_visible_ids(same), ["only-mine"])
        for request in [self.request("get", "/", user_id="other"), self.request("get", "/", proxy=True), self.request("get", "/", admin=False)]:
            request.auth_introspection = {"sessionId": "sid-2"}
            with patch.object(crm_source, "_request_payload", return_value={"items": []}):
                self.assertEqual(crm_source.crm_visible_ids(request), [])

    def test_background_permission_failure_clears_scope_and_unlocks_retry(self):
        self.seed_scope(2)
        request = self.request("get", "/")
        denied = crm_source.CrmSourceError("CRM 无权限", status=403, code="CRM_PERMISSION_DENIED")
        with patch.object(crm_source.threading, "Thread") as thread:
            crm_source._start_background_sync(request)
        callback = thread.call_args.kwargs["target"]
        with patch.object(crm_source, "close_old_connections"), patch.object(crm_source.connection, "close"), \
                patch.object(crm_source, "_request_payload", side_effect=denied):
            callback()
        key = crm_source._cache_key(request)
        self.assertIsNone(cache.get(key))
        self.assertIsNone(cache.get(key + ":lock"))
        response = views.projects_collection(self.request("get", "/", query={"type": "presales"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.data(response)["items"], [])
        self.assertEqual(self.data(response)["crmSyncError"], "CRM 无权限")

    def test_background_network_failure_does_not_extend_scope_or_destroy_tasks(self):
        self.seed_scope(2)
        request = self.request("get", "/")
        key = crm_source._cache_key(request)
        before = cache.get(key)
        with patch.object(crm_source.threading, "Thread") as thread:
            crm_source._start_background_sync(request)
        callback = thread.call_args.kwargs["target"]
        with patch.object(crm_source, "close_old_connections"), patch.object(crm_source.connection, "close"), \
                patch.object(crm_source, "_request_payload", side_effect=crm_source.CrmSourceError()):
            callback()
        self.assertEqual(cache.get(key), before)
        self.assertIsNone(cache.get(key + ":lock"))
        self.assertTrue(crm_source.crm_sync_status(request)["crmSyncError"])
        self.assertEqual(ServiceProject.objects.count(), 2)
        self.assertEqual(ProjectNode.objects.count(), 2)

    def test_sync_lease_expires_after_a_restart_and_old_worker_cannot_unlock_replacement(self):
        request = self.request("get", "/")
        key = crm_source._cache_key(request)
        with patch.object(crm_source.threading, "Thread") as thread, patch.object(cache, "add", wraps=cache.add) as add:
            crm_source._start_background_sync(request)
        self.assertEqual(add.call_args.kwargs["timeout"], 90)
        cache.set(key + ":lock", "replacement-worker", timeout=90)
        callback = thread.call_args.kwargs["target"]
        with patch.object(crm_source, "close_old_connections"), patch.object(crm_source.connection, "close"), \
                patch.object(crm_source, "urlopen", side_effect=AssertionError("old worker must not fetch")):
            callback()
        self.assertEqual(cache.get(key + ":lock"), "replacement-worker")
        self.assertIsNone(cache.get(key + ":error"))

    def test_list_expiry_matches_the_snapshot_actually_used_during_a_refresh(self):
        self.seed_scope(2)
        request = self.request("get", "/", query={"type": "presales"})
        key = crm_source._cache_key(request)
        old = cache.get(key)
        cache.delete(key + ":fresh")
        def finish_sync(_request):
            cache.set(key, {**old, "ids": [], "expiresAt": "2099-01-01T00:00:00+00:00"}, timeout=300)
        with patch.object(crm_source, "_in_memory_database", return_value=False), \
                patch.object(crm_source, "_start_background_sync", side_effect=finish_sync):
            payload = self.data(views.projects_collection(request))
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["crmScopeExpiresAt"], old["expiresAt"])

    def test_stale_scope_has_bounded_lifetime_and_denial_clears_it(self):
        self.seed_scope(2)
        request = self.request("get", "/")
        key = crm_source._cache_key(request)
        cache.delete(key + ":fresh")
        with patch.object(crm_source, "_in_memory_database", return_value=False), patch.object(crm_source.threading, "Thread"):
            response = views.projects_collection(self.request("get", "/", query={"type": "presales"}))
        self.assertEqual(self.data(response)["total"], 2)
        self.assertTrue(self.data(response)["crmSyncing"])
        cache.delete(key)
        with patch.object(crm_source, "_in_memory_database", return_value=False):
            response = views.projects_collection(self.request("get", "/", query={"type": "presales"}))
        self.assertEqual(self.data(response)["items"], [])
        crm_source._remember_error(request, crm_source.CrmSourceError("无权限", status=403, code="CRM_PERMISSION_DENIED"))
        response = views.projects_collection(self.request("get", "/", query={"type": "presales"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.data(response)["items"], [])
        self.assertEqual(self.data(response)["crmSyncError"], "无权限")
        self.assertIsNone(cache.get(key))

    def test_bulk_sync_skips_unchanged_rows_and_preserves_local_drafts_on_changed_rows(self):
        rows, projects = self.seed_scope(1500)
        # Lite snapshots include only source-owned fields.
        for row in rows:
            row.pop("customerId")
        ServiceProject.objects.bulk_update([
            self._set_snapshot(item, row) for item, row in zip(projects, rows)
        ], ["crm_snapshot"], batch_size=100)
        request = self.request("get", "/")
        with patch.object(crm_source, "_sync_row", side_effect=AssertionError("existing rows must not initialize workflows")), \
                CaptureQueriesContext(connection) as queries:
            crm_source._sync_rows(request, rows)
        self.assertEqual(len(queries), 1)
        target = projects[0]
        target.business_data = {"projectInfo": {"reason": "本地申请理由"}, "projectInfoRecords": {"saved": "历史资料"}}
        target.save()
        stamp = target.updated_at
        rows[0]["owner"] = "CRM 新负责人"
        crm_source._sync_rows(request, rows)
        target.refresh_from_db()
        self.assertEqual(target.owner_name, "CRM 新负责人")
        self.assertEqual(target.business_data["projectInfo"]["reason"], "本地申请理由")
        self.assertEqual(target.business_data["projectInfoRecords"], {"saved": "历史资料"})
        self.assertEqual(target.updated_at, stamp)
        self.assertEqual(ProjectNode.objects.count(), 1500)

    def test_large_dashboard_counts_all_records_but_only_reads_bounded_summaries(self):
        _, projects = self.seed_scope(full_nodes=True)
        ServiceProject.objects.all().update(created_by="system-admin", status="blocked")
        # Thousands of CRM projects belong to this creator, but only explicitly
        # assigned nodes count as their own pending tasks.
        ProjectNode.objects.filter(project__in=projects[:9], status="active").update(
            business_data={"managementAssignment": {"userId": "system-admin", "name": "管理员"}},
        )
        # Unassigned delivery work is still a project risk for its creator,
        # without increasing their personal pending-task count.
        for project, days in zip(projects[:2], (-1, 1)):
            node = project.nodes.get(node_key="early-plan")
            node.status = "active"
            node.business_data = {"schemeRounds": [{"plannedEndDate": (timezone.localdate() + timedelta(days=days)).isoformat()}]}
            node.save(update_fields=["status", "business_data"])
            sync_presales_task_schedules(node)
        provider = ServiceProvider.objects.create(auth_user_id="field-user", name="服务人员", role="installer")
        ServiceTicket.objects.bulk_create([
            ServiceTicket(code=f"dash-ticket-{item.pk}", project=item, title="紧急工单", ticket_type="异常",
                          priority="high", reporter_user_id="field-user", description="待处理")
            for item in projects
        ])
        FieldFeedback.objects.bulk_create([
            FieldFeedback(project=item, provider=provider, feedback_type="issue", content="待审核") for item in projects
        ])
        Reward.objects.bulk_create([
            Reward(code=f"dash-reward-{item.pk}", project=item, provider=provider, title="待发奖励", reward_type="cash")
            for item in projects
        ])
        request = self.request("get", "/api/after-sales/dashboard")
        with patch.object(crm_source, "_request_payload", side_effect=AssertionError("dashboard must reuse cached CRM scope")), \
                CaptureQueriesContext(connection) as queries:
            response = views.dashboard(request)
        payload = self.data(response)
        self.assertEqual(response.status_code, 200, payload)
        for key in ("projects", "activeProjects", "openTickets", "pendingFeedback", "pendingRewards"):
            self.assertEqual(payload["metrics"][key], 1500)
        self.assertEqual(payload["taskTotal"], 9)
        self.assertEqual(payload["alertTotal"], 3002)
        self.assertTrue(payload["crmScopeReady"])
        for key in ("tasks", "alerts", "recentProjects", "recentTickets"):
            self.assertEqual(len(payload[key]), 8)
        self.assertEqual({row["type"] for row in payload["alerts"]},
                         {"blocked_project", "high_priority_ticket", "overdue_presales_task", "due_presales_task"})
        self.assertNotIn("businessData", payload["recentProjects"][0])
        self.assertNotIn("businessData", payload["tasks"][0])
        self.assertLessEqual(len(queries), 24)  # Bounded active-node summaries for the eight recent projects.
        self.assertLess(len(response.content), 30000)

    def test_cold_dashboard_returns_local_work_without_waiting_for_crm(self):
        self.seed_scope(2)
        local = services.create_project(self.request("post", "/"), {
            "code": "dashboard-local", "name": "独立售中项目", "customer": "学校", "service_type": "midsales",
            "status": "in_progress", "owner_user_id": "another-user",
        })
        with patch.object(crm_source, "_in_memory_database", return_value=False), \
                patch.object(crm_source.threading, "Thread") as thread, \
                patch.object(crm_source, "_request_payload", side_effect=AssertionError("dashboard must not fetch CRM synchronously")):
            response = views.dashboard(self.request("get", "/", user_id="another-user"))
        payload = self.data(response)
        self.assertEqual(response.status_code, 200, payload)
        self.assertEqual(payload["metrics"]["activeProjects"], 1)
        self.assertEqual([item["id"] for item in payload["recentProjects"]], [local.pk])
        self.assertTrue(payload["crmSyncing"])
        self.assertFalse(payload["crmScopeReady"])
        thread.assert_called_once()

    def test_dashboard_network_or_permission_failure_never_hides_local_work_or_exposes_crm(self):
        self.seed_scope(2)
        ServiceProject.objects.all().update(created_by="system-admin")
        local = services.create_project(self.request("post", "/"), {
            "code": "dashboard-aftersales", "name": "本地售后", "customer": "学校", "service_type": "aftersales",
            "status": "in_progress",
        })
        for failure in [crm_source.CrmSourceError(), crm_source.CrmSourceError("CRM 无权限", status=403, code="CRM_PERMISSION_DENIED")]:
            with self.subTest(code=failure.code):
                cache.delete(crm_source._cache_key(self.request("get", "/")))
                crm_source._remember_error(self.request("get", "/"), failure)
                with patch.object(crm_source, "_in_memory_database", return_value=False), \
                        patch.object(crm_source, "_request_payload", side_effect=AssertionError("failure must be isolated")):
                    response = views.dashboard(self.request("get", "/"))
                payload = self.data(response)
                self.assertEqual(response.status_code, 200, payload)
                self.assertEqual(payload["metrics"]["activeProjects"], 1)
                self.assertEqual([item["id"] for item in payload["recentProjects"]], [local.pk])
                self.assertFalse(payload["crmScopeReady"])
                self.assertEqual(payload["crmSyncError"], str(failure))

    def test_dashboard_relogin_keeps_own_scope_and_never_uses_a_proxy_scope(self):
        rows, projects = self.seed_scope(3)
        ServiceProject.objects.all().update(created_by="system-admin")
        original = self.request("get", "/")
        original.auth_introspection = {"sessionId": "first-session"}
        crm_source._remember_scope(original, [rows[0]["id"]], synced=True)
        proxy = self.request("get", "/", proxy=True)
        proxy.auth_introspection = {"sessionId": "proxy-session"}
        crm_source._remember_scope(proxy, [rows[1]["id"]], synced=True)
        for session_id, proxying, expected in [("first-session", False, [projects[0].pk]),
                                               ("proxy-session", True, [projects[1].pk]),
                                               ("new-session", False, [projects[0].pk])]:
            request = self.request("get", "/", proxy=proxying)
            request.auth_introspection = {"sessionId": session_id}
            with patch.object(crm_source, "_in_memory_database", return_value=False), \
                    patch.object(crm_source.threading, "Thread"), \
                    patch.object(crm_source, "_request_payload", side_effect=AssertionError("must use this session's scope")):
                payload = self.data(views.dashboard(request))
            self.assertEqual([item["id"] for item in payload["recentProjects"]], expected)

    def test_dashboard_status_matches_snapshot_used_even_if_sync_finishes_during_request(self):
        rows, _projects = self.seed_scope(2)
        ServiceProject.objects.all().update(created_by="another-user")
        request = self.request("get", "/", user_id="another-user")
        def publish_snapshot(copied):
            crm_source._remember_scope(copied, [row["id"] for row in rows], synced=True)
        with patch.object(crm_source, "_in_memory_database", return_value=False), \
                patch.object(crm_source, "_start_background_sync", side_effect=publish_snapshot):
            first = self.data(views.dashboard(request))
        self.assertEqual(first["metrics"]["projects"], 0)
        self.assertFalse(first["crmScopeReady"])
        with patch.object(crm_source, "_request_payload", side_effect=AssertionError("scope is now cached")):
            second = self.data(views.dashboard(self.request("get", "/", user_id="another-user")))
        self.assertEqual(second["metrics"]["projects"], 2)
        self.assertTrue(second["crmScopeReady"])

    def test_dashboard_refresh_retries_background_sync_after_a_source_error(self):
        self.seed_scope(2)
        crm_source._remember_error(self.request("get", "/"), crm_source.CrmSourceError())
        with patch.object(crm_source, "_in_memory_database", return_value=False), \
                patch.object(crm_source.threading, "Thread") as thread, \
                patch.object(crm_source, "_request_payload", side_effect=AssertionError("retry must run in background")):
            payload = self.data(views.dashboard(self.request("get", "/", query={"crmRefresh": "1"})))
        thread.assert_called_once()
        self.assertTrue(payload["crmSyncing"])
        self.assertEqual(payload["crmSyncError"], "")

    @staticmethod
    def _set_snapshot(item, row):
        item.crm_snapshot = row
        return item
