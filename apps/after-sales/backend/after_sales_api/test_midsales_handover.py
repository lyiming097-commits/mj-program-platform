from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.utils import timezone

from . import attachment_views, crm_source, services, views
from .models import PrivateAttachment, ProjectNode, ServiceProject, ServiceProvider
from .tests import CleanDomainMixin, RequestMixin


class MidsalesHandoverTests(RequestMixin, CleanDomainMixin, TestCase):
    selected = ["midsales-project", "device-install", "project-acceptance", "midsales-project-end"]

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()
        self.addCleanup(cache.clear)
        self.clear_domain()
        self.project = services.create_project(self.request("post", "/"), {
            "code": "PS-HANDOVER", "service_type": "presales", "name": "交接项目",
            "customer": "测试学校", "owner_user_id": "sales-owner", "owner_name": "售前负责人",
            "address": "学校实验楼", "province": "浙江省", "summary": "交付说明",
        })
        # The full dependency graph is completed; only the explicit end remains.
        self.project.nodes.update(status="completed", completed_at=timezone.now())
        for key, outcome in [("early-approval", "approved"), ("late-approval", "approved"),
                             ("early-plan-result", "passed"), ("construction-result", "won")]:
            self.project.nodes.filter(node_key=key).update(business_data={"outcome": outcome})
        self.end = self.project.nodes.get(node_key="project-end")
        self.end.status = "active"
        self.end.completed_at = None
        self.end.save()
        self.project.current_node_key = "project-end"
        self.project.save()

    def advance(self, selected=None, *, project=None):
        source = project or self.project
        return views.project_advance(self.request("post", "/", {
            "nodeKey": "project-end", "businessData": {"midsalesNodeKeys": self.selected if selected is None else selected},
        }), source.id)

    def target(self):
        return ServiceProject.objects.get(presales_project=self.project)

    def archive(self, project=None, **identity):
        return views.project_presales_materials(self.request("get", "/", **identity), (project or self.target()).id)

    def attachment(self, node_key, category, name):
        return PrivateAttachment.objects.create(
            target_type="project_node", target_id=self.project.nodes.get(node_key=node_key).id,
            category=category, original_name=name, mime_type="application/pdf", size=123,
            file="handover-test/nonexistent.pdf", uploaded_by="system-admin",
        )

    def test_finishing_creates_selected_midsales_and_preserves_source(self):
        item = self.attachment("early-plan", "scheme_submission", "历史方案.pdf")
        source_nodes = list(self.project.nodes.exclude(pk=self.end.pk).values())
        response = self.advance()
        self.assertEqual(response.status_code, 200, self.data(response))
        target = self.target()
        self.assertEqual(self.data(response)["item"]["midsalesProjectId"], target.id)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "completed")
        self.assertEqual(target.service_type, "midsales")
        for key in ("name", "customer", "owner_user_id", "owner_name", "address", "province", "summary"):
            self.assertEqual(getattr(target, key), getattr(self.project, key))
        self.assertEqual(target.current_node_key, "midsales-project")
        self.assertEqual(set(target.nodes.filter(enabled=True).values_list("node_key", flat=True)), set(self.selected))
        self.assertTrue(all(state == "skipped" for state in target.nodes.filter(enabled=False).values_list("status", flat=True)))
        self.assertFalse(target.assignments.exists(), "DingTalk personnel must not become WeChat workers")
        self.assertEqual(list(self.project.nodes.exclude(pk=self.end.pk).values()), source_nodes)
        self.assertEqual(list(PrivateAttachment.objects.values_list("id", flat=True)), [item.id])
        self.assertTrue(self.project.events.filter(event_type="midsales_handover").exists())
        self.assertTrue(target.events.filter(event_type="presales_handover").exists())
        self.assertEqual(self.advance().status_code, 409)
        self.assertEqual(ServiceProject.objects.filter(presales_project=self.project).count(), 1)

    def test_invalid_selection_never_completes_source_or_creates_child(self):
        for selected in [[], "device-install", ["unknown"], ["device-install"],
                         ["midsales-project", "midsales-project-end", "device-install", "device-install"]]:
            with self.subTest(selected=selected):
                response = self.advance(selected)
                self.assertEqual(response.status_code, 400, self.data(response))
                self.assertEqual(self.data(response)["code"], "MIDSALES_HANDOVER_NODES_REQUIRED")
                self.end.refresh_from_db()
                self.assertEqual(self.end.status, "active")
                self.assertFalse(ServiceProject.objects.filter(presales_project=self.project).exists())

    def test_saved_selection_is_used_when_advance_does_not_repeat_it(self):
        self.end.business_data = {"midsalesNodeKeys": self.selected}
        self.end.save()
        response = views.project_advance(self.request("post", "/", {"nodeKey": "project-end"}), self.project.id)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertEqual(set(self.target().nodes.filter(enabled=True).values_list("node_key", flat=True)), set(self.selected))

    def test_handover_failure_rolls_back_completion_and_all_child_records(self):
        with patch("after_sales_api.midsales_handover.create_project", side_effect=services.DomainValidationError("建项失败")):
            response = self.advance()
        self.assertEqual(response.status_code, 400)
        self.project.refresh_from_db()
        self.end.refresh_from_db()
        self.assertEqual(self.project.status, "in_progress")
        self.assertEqual(self.end.status, "active")
        self.assertFalse(ServiceProject.objects.filter(presales_project=self.project).exists())
        self.assertFalse(self.project.events.filter(event_type="midsales_handover").exists())

    def test_reending_presales_reuses_child_without_resetting_midsales(self):
        self.assertEqual(self.advance().status_code, 200)
        target = self.target()
        target.business_data = {"preserve": "售中已填写的资料"}
        target.save()
        before = list(target.nodes.values())
        services.reopen_project_node(self.request("post", "/"), self.project.id, node_key="project-end")
        self.assertEqual(self.advance().status_code, 200)
        self.assertEqual(self.target().id, target.id)
        target.refresh_from_db()
        self.assertEqual(target.business_data, {"preserve": "售中已填写的资料"})
        self.assertEqual(list(target.nodes.values()), before)

    def test_unfinished_dependencies_and_cancelled_projects_cannot_handover(self):
        self.project.nodes.filter(node_key="construction").update(status="active")
        self.assertEqual(self.advance().status_code, 409)
        self.project.nodes.filter(node_key="construction").update(status="completed")
        ServiceProject.objects.filter(pk=self.project.id).update(status="cancelled")
        self.assertEqual(self.advance().status_code, 409)
        self.assertFalse(ServiceProject.objects.filter(presales_project=self.project).exists())

    def test_archive_collects_all_rounds_and_keeps_other_categories_without_copying(self):
        old = self.attachment("early-plan", "scheme_submission", "第一轮.pdf")
        latest = self.attachment("early-plan", "scheme_submission", "第二轮.pdf")
        inherited = self.attachment("early-plan", "scheme_submission", "保留的附件.pdf")
        removed = self.attachment("early-plan", "scheme_submission", "最新轮已移除.pdf")
        other_node = self.attachment("device-plan", "scheme_submission", "另一节点最新轮.pdf")
        self.attachment("budget", "fee_estimated", "预算清单.pdf")
        self.attachment("early-approval", "general", "立项附件.pdf")
        self.project.nodes.filter(node_key="early-plan").update(business_data={
            "schemeRounds": [{"attachmentIds": [old.id, inherited.id, removed.id]},
                             {"attachmentIds": [str(latest.id), inherited.id, inherited.id, other_node.id]}],
        })
        self.project.nodes.filter(node_key="device-plan").update(business_data={
            "schemeRounds": [{"attachmentIds": []}, {"attachmentIds": [other_node.id]}],
        })
        self.assertEqual(self.advance().status_code, 200)
        response = self.archive()
        self.assertEqual(response.status_code, 200, self.data(response))
        data = self.data(response)
        self.assertEqual(data["project"]["id"], self.project.id)
        self.assertEqual(data["attachmentCount"], 7)
        groups = {row["nodeKey"]: row for row in data["groups"]}
        self.assertEqual(groups["early-plan"]["attachmentCount"], 4)
        self.assertEqual(set(groups["early-plan"]["itemIds"]), {old.id, latest.id, inherited.id, removed.id})
        self.assertEqual(groups["device-plan"]["itemIds"], [other_node.id])
        self.assertEqual(groups["budget"]["categories"], [{"value": "fee_estimated", "label": "预计费用清单"}])
        self.assertEqual(PrivateAttachment.objects.count(), 7)
        self.assertNotIn("files", data)
        denied = attachment_views.attachment_item(self.request("delete", "/"), old.id)
        self.assertEqual(denied.status_code, 409)

    def test_empty_latest_round_keeps_history_but_excludes_unassigned_and_reason_files(self):
        old = self.attachment("early-plan", "scheme_submission", "第一轮.pdf")
        self.attachment("early-plan", "scheme_submission", "未关联轮次.pdf")
        reason = self.attachment("early-plan", "scheme_submission", "新增原因.pdf")
        general = self.attachment("early-plan", "general", "普通节点资料.pdf")
        self.project.nodes.filter(node_key="early-plan").update(business_data={
            "schemeRounds": [{"attachmentIds": [old.id]}, {"attachmentIds": [], "reasonAttachmentIds": [reason.id]}],
        })
        self.assertEqual(self.advance().status_code, 200)
        data = self.data(self.archive())
        self.assertEqual(data["attachmentCount"], 2)
        self.assertEqual(set(data["groups"][0]["itemIds"]), {old.id, general.id})
        self.assertEqual(data["groups"][0]["categories"], [
            {"value": "general", "label": "普通附件"},
            {"value": "scheme_submission", "label": "方案提交附件"},
        ])

    def test_same_name_submissions_use_upload_time_across_nodes_and_rounds(self):
        latest = self.attachment("device-plan", "scheme_submission", "方案.pdf")
        older = self.attachment("early-plan", "scheme_submission", "方案.pdf")
        different_extension = self.attachment("early-plan", "scheme_submission", "方案.xlsx")
        first_tie = self.attachment("early-plan", "scheme_submission", "图纸.dwg")
        last_tie = self.attachment("early-plan", "scheme_submission", "图纸.dwg")
        now = timezone.now()
        PrivateAttachment.objects.filter(pk=older.pk).update(created_at=now - timedelta(days=1))
        PrivateAttachment.objects.filter(pk=latest.pk).update(created_at=now)
        PrivateAttachment.objects.filter(pk__in=[first_tie.pk, last_tie.pk]).update(created_at=now)
        # Newer excluded uploads must never hide valid older submissions.
        orphan = self.attachment("device-plan", "scheme_submission", "方案.pdf")
        reason = self.attachment("device-plan", "scheme_submission", "图纸.dwg")
        unrelated = services.create_project(self.request("post", "/"), {
            "code": "PS-OTHER", "service_type": "presales", "name": "另一项目", "customer": "学校",
        })
        PrivateAttachment.objects.create(
            target_type="project_node", target_id=unrelated.nodes.get(node_key="early-plan").pk,
            category="scheme_submission", original_name="方案.pdf", mime_type="application/pdf",
            size=12, file="test-not-stored.pdf", uploaded_by="system-admin",
        )
        self.project.nodes.filter(node_key="early-plan").update(business_data={
            "schemeRounds": [{"attachmentIds": [older.id, first_tie.id]},
                             {"attachmentIds": [different_extension.id, last_tie.id]}],
        })
        self.project.nodes.filter(node_key="device-plan").update(business_data={
            "schemeRounds": [{"attachmentIds": [latest.id], "reasonAttachmentIds": [reason.id]}],
        })
        self.assertEqual(self.advance().status_code, 200)
        data = self.data(self.archive())
        self.assertEqual(data["attachmentCount"], 3)
        groups = {row["nodeKey"]: row for row in data["groups"]}
        self.assertEqual(groups["device-plan"]["itemIds"], [latest.id])
        self.assertEqual(set(groups["early-plan"]["itemIds"]), {different_extension.id, last_tie.id})
        self.assertEqual(groups["early-plan"]["attachmentCount"], 2)
        self.assertEqual(groups["device-plan"]["attachmentCount"], 1)
        self.assertEqual(groups["early-plan"]["categories"], [
            {"value": "scheme_submission", "label": "方案提交附件"},
        ])
        self.assertEqual(PrivateAttachment.objects.filter(pk__in=[older.id, first_tie.id, orphan.id, reason.id]).count(), 4)

    def test_project_requirement_documents_are_visible_in_midsales_materials_without_copying(self):
        legacy = self.attachment("early-approval", "general", "原立项需求.pdf")
        item = PrivateAttachment.objects.create(
            target_type="presales_project", target_id=self.project.pk, category="general",
            file="test-not-stored.pdf", original_name="项目需求.pdf", mime_type="application/pdf",
            size=12, uploaded_by="system-admin",
        )
        self.assertEqual(self.advance().status_code, 200)
        data = self.data(self.archive())
        self.assertEqual(data["attachmentCount"], 2)
        group = next(row for row in data["groups"] if row["targetType"] == "presales_project")
        self.assertEqual(group["name"], "项目需求文档")
        self.assertEqual(group["itemIds"], [item.pk], "legacy files stay in their original node group")
        self.assertEqual(PrivateAttachment.objects.count(), 2)
        self.assertTrue(PrivateAttachment.objects.filter(pk=legacy.pk, target_type="project_node").exists())

    def test_crm_permissions_are_rechecked_for_handover_and_archive(self):
        self.project.source_crm_id = "original-crm"
        self.project.save()
        failure = crm_source.CrmSourceError("无 CRM 权限", status=403, code="CRM_PERMISSION_DENIED")
        with patch.object(crm_source, "_request_payload", side_effect=failure):
            self.assertEqual(self.advance().status_code, 403)
        with patch.object(crm_source, "_request_payload", return_value={"item": {"id": "original-crm"}}):
            self.assertEqual(self.advance().status_code, 200)
            response = self.archive()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.data(response)["project"]["sourceCrmId"], "original-crm")
        with patch.object(crm_source, "_request_payload", side_effect=failure):
            self.assertEqual(self.archive().status_code, 403)
            response = self.archive(user_id="other-user", admin=False)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.data(response)["code"], "APP_ACCESS_DENIED")

    def test_mobile_users_are_not_granted_presales_material_access(self):
        self.assertEqual(self.advance().status_code, 200)
        ServiceProvider.objects.create(auth_user_id="wx-worker", name="现场人员", certification_status="certified")
        self.assertEqual(self.archive(user_id="wx-worker", admin=False).status_code, 403)

    def test_manual_midsales_has_empty_archive_and_deleted_source_is_not_exposed(self):
        manual = services.create_project(self.request("post", "/"), {
            "code": "MS-MANUAL", "service_type": "midsales", "name": "独立售中", "customer": "学校",
        })
        self.assertEqual(self.data(self.archive(manual)), {"project": None, "groups": [], "attachmentCount": 0})
        self.assertEqual(self.advance().status_code, 200)
        ServiceProject.objects.filter(pk=self.project.id).update(deleted_at=timezone.now())
        self.assertEqual(self.archive().status_code, 404)
