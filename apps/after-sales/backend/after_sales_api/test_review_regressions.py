import json
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from . import approval_views, attachment_views, proof_views, views
from .approval_models import PresalesApprovalStep
from .models import FieldFeedback, MidsalesProof, PrivateAttachment, ProjectAssignment, ProjectNode, Reward, RewardPrize, ServiceProject, ServiceProvider, ServiceTicket
from .serializers import project_draft_version


class ReviewRegressionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings = override_settings(MEDIA_ROOT=self.media.name)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.provider = ServiceProvider.objects.create(auth_user_id="wxmini:review", name="测试服务人员", certification_status="certified")
        self.project = ServiceProject.objects.create(code="REVIEW-1", name="隔离回归项目", customer="测试客户", service_type="midsales", status="in_progress", current_node_key="device-install")
        self.node = ProjectNode.objects.create(project=self.project, node_key="device-install", name="设备安装", kind="delivery", sequence=1, status="active", actual_start_at=timezone.now())
        self.assignment = ProjectAssignment.objects.create(project=self.project, node=self.node, provider=self.provider, status="in_progress")

    def request(self, method="get", payload=None, *, admin=False, user=None, multipart=False):
        method_fn = getattr(self.factory, method)
        if method == "get" or multipart:
            request = method_fn("/", payload or {})
        else:
            request = method_fn("/", json.dumps(payload or {}), content_type="application/json")
        request.auth_user_id = user or ("review-admin" if admin else self.provider.auth_user_id)
        request.auth_user_name = request.auth_user_id
        request.auth_actor_user_id = request.auth_user_id
        request.auth_actor_name = request.auth_user_id
        request.auth_is_proxy = False
        request.auth_can_use_system_admin = admin
        request.auth_token_claims = {"chn": "dingtalk" if admin else "wechat-mini"}
        return request

    @staticmethod
    def data(response):
        return json.loads(response.content)

    def upload(self, target_type="project_node", target_id=None):
        return attachment_views.attachments_collection(self.request("post", {
            "targetType": target_type, "targetId": target_id or self.node.id,
            "file": SimpleUploadedFile("evidence.jpg", b"image-data", content_type="image/jpeg"),
        }, multipart=True))

    def test_paused_or_pending_provider_cannot_access_business_files_but_can_maintain_own_application(self):
        uploaded = self.upload()
        self.assertEqual(uploaded.status_code, 201, uploaded.content)
        attachment_id = self.data(uploaded)["item"]["id"]
        for status in ("paused", "pending"):
            self.provider.certification_status = status
            self.provider.save()
            listing = attachment_views.attachments_collection(self.request(payload={"targetType": "project_node", "targetId": self.node.id}))
            self.assertEqual(listing.status_code, 403)
            self.assertEqual(self.upload().status_code, 403)
            self.assertEqual(attachment_views.attachment_download(self.request(), attachment_id).status_code, 404)
            self.assertEqual(attachment_views.attachment_item(self.request("delete"), attachment_id).status_code, 404)
            self.assertEqual(self.upload("provider_application", self.provider.id).status_code, 201)

    def test_completed_assignment_locks_files_but_retains_download(self):
        uploaded = self.upload()
        attachment_id = self.data(uploaded)["item"]["id"]
        self.assignment.status = "completed"
        self.assignment.save()
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(attachment_views.attachment_item(self.request("delete"), attachment_id).status_code, 409)
        listing = attachment_views.attachments_collection(self.request(payload={"targetType": "project_node", "targetId": self.node.id}))
        self.assertFalse(self.data(listing)["items"][0]["canDelete"])
        download = attachment_views.attachment_download(self.request(), attachment_id)
        self.assertEqual(download.status_code, 200)
        download.close()
        proof = MidsalesProof.objects.create(node=self.node, proof_type="process")
        self.assertEqual(self.upload("midsales_proof", proof.id).status_code, 409)

    def test_approved_proof_is_immutable_and_rejected_proof_can_be_corrected(self):
        proof = MidsalesProof.objects.create(node=self.node, proof_type="process")
        uploaded = self.upload("midsales_proof", proof.id)
        attachment_id = self.data(uploaded)["item"]["id"]
        reviewed = proof_views.midsales_proof_review(self.request("post", {"status": "approved"}, admin=True), self.project.id, self.node.node_key, "process")
        self.assertEqual(reviewed.status_code, 200, reviewed.content)
        for admin in (False, True):
            deleted = attachment_views.attachment_item(self.request("delete", admin=admin), attachment_id)
            self.assertEqual(deleted.status_code, 409, deleted.content)
        self.assertEqual(self.upload("midsales_proof", proof.id).status_code, 409)
        listing = proof_views.midsales_proofs(self.request(), self.project.id, self.node.node_key)
        row = next(item for item in self.data(listing)["items"] if item["proofType"] == "process")
        self.assertFalse(row["canUpload"])
        self.assertFalse(row["attachments"][0]["canDelete"])
        attachment = PrivateAttachment.objects.get(pk=attachment_id)
        self.assertTrue(attachment.file.storage.exists(attachment.file.name))
        rejected = proof_views.midsales_proof_review(self.request("post", {"status": "rejected", "opinion": "请更正"}, admin=True), self.project.id, self.node.node_key, "process")
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(attachment_views.attachment_item(self.request("delete"), attachment_id).status_code, 200)

    def test_plain_node_and_project_autosaves_reject_stale_versions(self):
        self.node.business_data = {"externalQuote": "100", "deliveryNote": "初始"}
        self.node.save()
        version = self.node.updated_at.isoformat()
        for quote, expected_status in (("200", 200), ("100", 409)):
            response = views.project_node_autosave(self.request("patch", {"expectedUpdatedAt": version, "businessData": {"externalQuote": quote}}, admin=True), self.project.id, self.node.node_key)
            self.assertEqual(response.status_code, expected_status, response.content)
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["externalQuote"], "200.00")
        self.project.refresh_from_db()
        version = self.project.updated_at.isoformat()
        for note, expected_status in (("新版资料", 200), ("旧页覆盖", 409)):
            response = views.project_item(self.request("patch", {"expectedUpdatedAt": version, "businessData": {"note": note}}, admin=True), self.project.id)
            self.assertEqual(response.status_code, expected_status, response.content)
        self.project.refresh_from_db()
        self.assertEqual(self.project.business_data["note"], "新版资料")

    def test_identical_project_autosaves_do_not_write_history_or_audit_stamps(self):
        self.project.business_data = {"note": "原项目资料", "zero": 0}
        self.project.save()
        stamp = self.project.updated_at.isoformat()
        for payload in ({}, {"name": self.project.name}, {"businessData": self.project.business_data}):
            response = views.project_item(self.request("patch", {
                **payload, "expectedUpdatedAt": stamp,
            }, admin=True), self.project.id)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(self.data(response)["item"]["updatedAt"], stamp)
        self.project.refresh_from_db()
        self.assertEqual(self.project.updated_by, "")
        self.assertEqual(self.project.events.count(), 0)

        # A redundant save still enforces optimistic locking and permissions.
        stale = views.project_item(self.request("patch", {
            "expectedUpdatedAt": "stale", "name": self.project.name,
        }, admin=True), self.project.id)
        self.assertEqual(stale.status_code, 409, stale.content)
        forbidden = views.project_item(self.request("patch", {"name": self.project.name}), self.project.id)
        self.assertEqual(forbidden.status_code, 403, forbidden.content)

    def test_identical_node_autosave_preserves_project_and_node_audit_stamps(self):
        self.node.business_data = {"deliveryNote": "原备注"}
        self.node.save()
        stamp = self.node.updated_at.isoformat()
        project_stamp = self.project.updated_at
        for values in ({}, {"businessData": {"deliveryNote": "原备注"}}):
            response = views.project_node_autosave(self.request("patch", {
                **values, "expectedUpdatedAt": stamp,
            }, admin=True), self.project.id, self.node.node_key)
            self.assertEqual(response.status_code, 200, response.content)
        self.node.refresh_from_db()
        self.project.refresh_from_db()
        self.assertEqual(self.node.updated_at.isoformat(), stamp)
        self.assertEqual(self.project.updated_at, project_stamp)
        self.assertEqual(self.node.updated_by, "")
        self.assertEqual(self.project.events.count(), 0)
        stale = views.project_node_autosave(self.request("patch", {
            "businessData": {"deliveryNote": "原备注"}, "expectedUpdatedAt": "stale",
        }, admin=True), self.project.id, self.node.node_key)
        self.assertEqual(stale.status_code, 409, stale.content)

    def test_project_draft_version_ignores_node_activity_but_rejects_changed_project_info(self):
        version = project_draft_version(self.project)
        updated = views.project_node_autosave(self.request("patch", {
            "expectedUpdatedAt": self.node.updated_at.isoformat(), "businessData": {"externalQuote": "200"},
        }, admin=True), self.project.id, self.node.node_key)
        self.assertEqual(updated.status_code, 200, updated.content)
        self.project.refresh_from_db()
        self.assertEqual(project_draft_version(self.project), version)
        for note, expected_status in (("新项目资料", 200), ("过期项目资料", 409)):
            response = views.project_item(self.request("patch", {
                "expectedDraftVersion": version, "businessData": {"note": note},
            }, admin=True), self.project.id)
            self.assertEqual(response.status_code, expected_status, response.content)
        self.project.refresh_from_db()
        self.assertEqual(self.project.business_data["note"], "新项目资料")

    def test_assignment_and_schedule_share_node_version(self):
        version = self.node.updated_at.isoformat()
        assigned = views.project_assignments(self.request("post", {
            "nodeKey": self.node.node_key, "providerId": self.provider.id, "expectedUpdatedAt": version,
        }, admin=True), self.project.id)
        self.assertEqual(assigned.status_code, 201, assigned.content)
        current = self.data(assigned)["item"]["nodeUpdatedAt"]
        self.assertNotEqual(current, version)
        stale = views.project_assignments(self.request("post", {
            "nodeKey": self.node.node_key, "providerId": self.provider.id,
            "expectedUpdatedAt": version, "note": "过期页面覆盖",
        }, admin=True), self.project.id)
        self.assertEqual(stale.status_code, 409, stale.content)
        saved = views.project_node_autosave(self.request("patch", {
            "expectedUpdatedAt": current, "plannedEndAt": "2026-12-31T18:00:00+08:00",
        }, admin=True), self.project.id, self.node.node_key)
        self.assertEqual(saved.status_code, 200, saved.content)

    def test_mobile_records_paginate_all_history_and_keep_ownership(self):
        outsider = ServiceProvider.objects.create(auth_user_id="wxmini:outsider", name="其他人员", certification_status="certified")
        for index in range(21):
            FieldFeedback.objects.create(project=self.project, node=self.node, provider=self.provider, content=str(index))
            Reward.objects.create(code=f"RR-{index}", provider=self.provider, project=self.project, title=str(index))
            ServiceTicket.objects.create(code=f"RT-{index}", project=self.project, node=self.node, title=str(index), reporter_user_id=self.provider.auth_user_id)
        for index in range(25):
            FieldFeedback.objects.create(project=self.project, provider=outsider, content="其他人的反馈")
            Reward.objects.create(code=f"OTHER-{index}", provider=outsider, title="其他人的奖励")
            ServiceTicket.objects.create(code=f"OT-{index}", project=self.project, title="其他人的工单", reporter_user_id=outsider.auth_user_id)
        for record_type in ("feedback", "rewards", "tickets"):
            first = views.mobile_records(self.request(payload={"page": 1}), record_type)
            second = views.mobile_records(self.request(payload={"page": 2}), record_type)
            self.assertEqual(first.status_code, 200, first.content)
            self.assertEqual(self.data(first)["total"], 21)
            self.assertEqual(len(self.data(first)["items"]), 20)
            self.assertEqual(len(self.data(second)["items"]), 1)
            self.assertNotIn(self.data(second)["items"][0]["id"], [item["id"] for item in self.data(first)["items"]])
        old_reward = Reward.objects.get(code="RR-0")
        detail = views.mobile_records(self.request(payload={"recordId": old_reward.id}), "rewards")
        self.assertEqual(self.data(detail)["items"][0]["id"], old_reward.id)
        denied = views.mobile_records(self.request(payload={"recordId": old_reward.id}, user=outsider.auth_user_id), "rewards")
        self.assertEqual(self.data(denied)["items"], [])
        self.provider.certification_status = "paused"
        self.provider.save()
        self.assertEqual(views.mobile_records(self.request(), "rewards").status_code, 403)

    def test_feedback_prizes_use_active_catalog_and_snapshot(self):
        feedback = FieldFeedback.objects.create(project=self.project, provider=self.provider, feedback_type="reward_application", content="奖励申请")
        prize = RewardPrize.objects.create(name="工具包", enabled=False)
        for reward in ({"prize": "随意填写"}, {"prizeId": prize.id}):
            response = views.feedback_review(self.request("post", {"status": "accepted", "reward": reward}, admin=True), feedback.id)
            self.assertEqual(response.status_code, 400, response.content)
            feedback.refresh_from_db()
            self.assertEqual(feedback.status, "submitted")
            self.assertFalse(Reward.objects.filter(feedback=feedback).exists())
        prize.enabled = True
        prize.save()
        response = views.feedback_review(self.request("post", {"status": "accepted", "reward": {"prizeId": prize.id, "prize": "伪造名称"}}, admin=True), feedback.id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Reward.objects.get(feedback=feedback).prize, "工具包")
        no_prize = FieldFeedback.objects.create(project=self.project, provider=self.provider, feedback_type="reward_application", content="不配置奖品")
        response = views.feedback_review(self.request("post", {"status": "accepted"}, admin=True), no_prize.id)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Reward.objects.filter(feedback=no_prize).exists())

    def test_legacy_approvals_cannot_write_closed_nodes_even_on_get(self):
        self.project.service_type = "presales"
        self.project.status = "completed"
        self.project.save()
        self.node.node_key = "early-approval"
        self.node.kind = "approval"
        self.node.status = "completed"
        self.node.save()
        before = dict(self.node.business_data)
        response = approval_views.presales_approvals(self.request(admin=True), self.project.id, self.node.node_key)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.data(response)["items"], [])
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data, before)
        created = approval_views.presales_approvals(self.request("post", {"title": "新增审批", "approverName": "审批人"}, admin=True), self.project.id, self.node.node_key)
        self.assertEqual(created.status_code, 409)
        step = PresalesApprovalStep.objects.create(node=self.node, sequence=1, title="原始审批", approver_name="原审批人")
        for method in ("patch", "delete"):
            response = approval_views.presales_approval_item(self.request(method, {"title": "改写历史"}, admin=True), self.project.id, self.node.node_key, step.id)
            self.assertEqual(response.status_code, 409)
        step.refresh_from_db()
        self.assertEqual(step.title, "原始审批")
