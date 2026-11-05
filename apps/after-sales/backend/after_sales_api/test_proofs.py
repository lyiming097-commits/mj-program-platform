from __future__ import annotations

import json
from pathlib import Path
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings

from . import attachment_views, proof_views
from .models import (
    AppPermissionRule,
    MidsalesProof,
    PrivateAttachment,
    ProjectAssignment,
    ProjectEvent,
    ProjectNode,
    ServiceProject,
    ServiceProvider,
)


class MidsalesProofTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.media_directory = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=Path(self.media_directory.name))
        self.media_override.enable()
        AppPermissionRule.objects.all().delete()
        self.provider = ServiceProvider.objects.create(
            auth_user_id="proof-provider",
            name="证明上传人员",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        self.outsider = ServiceProvider.objects.create(
            auth_user_id="proof-outsider",
            name="无关人员",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        self.project = ServiceProject.objects.create(
            code="PROOF-MS-001",
            service_type=ServiceProject.TYPE_MIDSALES,
            name="售中证明项目",
            customer="测试客户",
            status=ServiceProject.STATUS_IN_PROGRESS,
            current_node_key="device-install",
        )
        self.node = ProjectNode.objects.create(
            project=self.project,
            node_key="device-install",
            name="设备安装",
            sequence=1,
            status=ProjectNode.STATUS_ACTIVE,
        )
        ProjectAssignment.objects.create(
            project=self.project,
            node=self.node,
            provider=self.provider,
            status=ProjectAssignment.STATUS_ASSIGNED,
        )

    def tearDown(self):
        self.media_override.disable()
        self.media_directory.cleanup()

    def authenticated(self, request, user_id: str, *, admin: bool = False):
        request.auth_user_id = user_id
        request.auth_user_name = user_id
        request.auth_actor_user_id = user_id
        request.auth_actor_name = user_id
        request.auth_is_proxy = False
        request.auth_can_use_system_admin = admin
        request.auth_token_claims = {"chn": "dingtalk" if admin else "wechat-mini"}
        return request

    @staticmethod
    def data(response) -> dict:
        return json.loads(response.content.decode("utf-8"))

    def list_proofs(self, user_id: str, *, admin: bool = False, mobile: bool = False):
        request = self.authenticated(
            self.factory.get(
                "/api/after-sales/projects/1/nodes/device-install/proofs",
                {"source": "mobile"} if mobile else None,
            ),
            user_id,
            admin=admin,
        )
        if mobile:
            request.auth_token_claims = {"chn": "wechat-mini", "aud": "after-sales-mobile"}
        return proof_views.midsales_proofs(request, self.project.id, self.node.node_key)

    def upload(
        self,
        proof: MidsalesProof,
        upload: SimpleUploadedFile,
        user_id: str,
        *,
        admin: bool = False,
        mobile: bool = False,
    ):
        request = self.authenticated(
            self.factory.post(
                "/api/after-sales/attachments",
                {
                    "targetType": PrivateAttachment.TARGET_MIDSALES_PROOF,
                    "targetId": str(proof.id),
                    **({"source": "mobile"} if mobile else {}),
                    "file": upload,
                },
            ),
            user_id,
            admin=admin,
        )
        if mobile:
            request.auth_token_claims = {"chn": "wechat-mini", "aud": "after-sales-mobile"}
        return attachment_views.attachments_collection(request)

    def review(self, proof_type: str, payload: dict, user_id: str, *, admin: bool = False):
        request = self.authenticated(
            self.factory.post(
                "/api/after-sales/projects/1/nodes/device-install/proofs/review",
                data=json.dumps(payload, ensure_ascii=False),
                content_type="application/json",
            ),
            user_id,
            admin=admin,
        )
        return proof_views.midsales_proof_review(
            request,
            self.project.id,
            self.node.node_key,
            proof_type,
        )

    def test_assigned_provider_lists_and_uploads_three_proof_types(self):
        response = self.list_proofs(self.provider.auth_user_id)
        self.assertEqual(response.status_code, 200)
        items = self.data(response)["items"]
        self.assertEqual([item["proofType"] for item in items], ["process", "completion", "evaluation"])
        self.assertTrue(all(item["canUpload"] for item in items))
        self.assertTrue(all(not item["canReview"] for item in items))

        dual_role = self.list_proofs(self.provider.auth_user_id, admin=True, mobile=True)
        self.assertEqual(dual_role.status_code, 200)
        self.assertTrue(all(item["canUpload"] for item in self.data(dual_role)["items"]))
        self.assertTrue(all(not item["canReview"] for item in self.data(dual_role)["items"]))

        process = MidsalesProof.objects.get(node=self.node, proof_type=MidsalesProof.TYPE_PROCESS)
        response = self.upload(
            process,
            SimpleUploadedFile("process.jpg", b"image", content_type="image/jpeg"),
            self.provider.auth_user_id,
            admin=True,
            mobile=True,
        )
        self.assertEqual(response.status_code, 201)

        response = self.upload(
            process,
            SimpleUploadedFile("process.pdf", b"pdf", content_type="application/pdf"),
            self.provider.auth_user_id,
        )
        self.assertEqual(response.status_code, 201, self.data(response))

        for proof_type in (MidsalesProof.TYPE_COMPLETION, MidsalesProof.TYPE_EVALUATION):
            proof = MidsalesProof.objects.get(node=self.node, proof_type=proof_type)
            response = self.upload(proof, SimpleUploadedFile(
                "交付资料.dwg", b"drawing", content_type="application/octet-stream",
            ), self.provider.auth_user_id)
            self.assertEqual(response.status_code, 201, self.data(response))

        response = self.list_proofs(self.provider.auth_user_id)
        process_data = next(item for item in self.data(response)["items"] if item["proofType"] == "process")
        self.assertEqual(len(process_data["attachments"]), 2)
        self.assertTrue(process_data["attachments"][0]["canDelete"])

    def test_unassigned_provider_cannot_see_or_upload_proofs(self):
        response = self.list_proofs(self.outsider.auth_user_id)
        self.assertEqual(response.status_code, 404)
        proof = MidsalesProof.objects.create(node=self.node, proof_type=MidsalesProof.TYPE_PROCESS)
        response = self.upload(
            proof,
            SimpleUploadedFile("process.jpg", b"image", content_type="image/jpeg"),
            self.outsider.auth_user_id,
        )
        self.assertEqual(response.status_code, 404)

    def test_only_admin_reviews_and_review_rules_are_enforced(self):
        self.list_proofs(self.provider.auth_user_id)
        admin_list = self.list_proofs("proof-admin", admin=True)
        self.assertTrue(all(not item["canUpload"] for item in self.data(admin_list)["items"]))
        proof = MidsalesProof.objects.get(node=self.node, proof_type=MidsalesProof.TYPE_PROCESS)
        admin_upload = self.upload(
            proof,
            SimpleUploadedFile("admin.jpg", b"image", content_type="image/jpeg"),
            "proof-admin",
            admin=True,
        )
        self.assertEqual(admin_upload.status_code, 403)
        self.assertEqual(self.data(admin_upload)["code"], "MIDSALES_ATTACHMENT_FIELD_UPLOAD_ONLY")

        response = self.review(
            MidsalesProof.TYPE_PROCESS,
            {"status": MidsalesProof.STATUS_APPROVED},
            self.provider.auth_user_id,
        )
        self.assertEqual(response.status_code, 403)

        response = self.review(
            MidsalesProof.TYPE_PROCESS,
            {"status": MidsalesProof.STATUS_APPROVED},
            "proof-admin",
            admin=True,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.data(response)["code"], "MIDSALES_PROOF_FILE_REQUIRED")

        field_upload = self.upload(
            proof,
            SimpleUploadedFile("process.jpg", b"image", content_type="image/jpeg"),
            self.provider.auth_user_id,
        )
        attachment_id = self.data(field_upload)["item"]["id"]
        admin_list = self.list_proofs("proof-admin", admin=True)
        process_data = next(item for item in self.data(admin_list)["items"] if item["proofType"] == "process")
        self.assertFalse(process_data["attachments"][0]["canDelete"])
        delete_request = self.authenticated(
            self.factory.delete(f"/api/after-sales/attachments/{attachment_id}"),
            "proof-admin",
            admin=True,
        )
        delete_response = attachment_views.attachment_item(delete_request, attachment_id)
        self.assertEqual(delete_response.status_code, 403)
        self.assertTrue(PrivateAttachment.objects.filter(pk=attachment_id).exists())
        response = self.review(
            MidsalesProof.TYPE_PROCESS,
            {"status": MidsalesProof.STATUS_APPROVED, "opinion": "材料符合要求"},
            "proof-admin",
            admin=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.data(response)["item"]["status"], MidsalesProof.STATUS_APPROVED)
        self.assertTrue(ProjectEvent.objects.filter(event_type="midsales_proof_review").exists())

        response = self.review(
            MidsalesProof.TYPE_COMPLETION,
            {"status": MidsalesProof.STATUS_REJECTED},
            "proof-admin",
            admin=True,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.data(response)["code"], "MIDSALES_PROOF_REJECT_REASON_REQUIRED")

    def test_project_acceptance_delivery_attachment_is_field_owned(self):
        node = ProjectNode.objects.create(
            project=self.project,
            node_key="project-acceptance",
            name="项目验收",
            sequence=2,
            kind="approval",
            status=ProjectNode.STATUS_ACTIVE,
        )
        ProjectAssignment.objects.create(
            project=self.project,
            node=node,
            provider=self.provider,
            status=ProjectAssignment.STATUS_ASSIGNED,
        )

        def upload(user_id, *, admin=False):
            request = self.authenticated(
                self.factory.post(
                    "/api/after-sales/attachments",
                    {
                        "targetType": PrivateAttachment.TARGET_PROJECT_NODE,
                        "targetId": str(node.id),
                        "category": PrivateAttachment.CATEGORY_GENERAL,
                        "file": SimpleUploadedFile("acceptance.pdf", b"pdf", content_type="application/pdf"),
                    },
                ),
                user_id,
                admin=admin,
            )
            return attachment_views.attachments_collection(request)

        admin_upload = upload("proof-admin", admin=True)
        self.assertEqual(admin_upload.status_code, 403)
        self.assertEqual(self.data(admin_upload)["code"], "MIDSALES_ATTACHMENT_FIELD_UPLOAD_ONLY")
        field_upload = upload(self.provider.auth_user_id)
        self.assertEqual(field_upload.status_code, 201)

    def test_midsales_fee_attachment_ownership_matches_fee_source(self):
        def upload(category: str, user_id: str, *, admin: bool = False, mobile: bool = False):
            request = self.authenticated(
                self.factory.post(
                    "/api/after-sales/attachments",
                    {
                        "targetType": PrivateAttachment.TARGET_PROJECT_NODE,
                        "targetId": str(self.node.id),
                        "category": category,
                        **({"source": "mobile"} if mobile else {}),
                        "file": SimpleUploadedFile(f"{category}.jpg", b"image", content_type="image/jpeg"),
                    },
                ),
                user_id,
                admin=admin,
            )
            if mobile:
                request.auth_token_claims = {"chn": "wechat-mini", "aud": "after-sales-mobile"}
            return attachment_views.attachments_collection(request)

        estimated = upload(PrivateAttachment.CATEGORY_FEE_ESTIMATED, "proof-admin", admin=True)
        self.assertEqual(estimated.status_code, 201)
        denied_estimated = upload(PrivateAttachment.CATEGORY_FEE_ESTIMATED, self.provider.auth_user_id)
        self.assertEqual(denied_estimated.status_code, 403)
        self.assertEqual(self.data(denied_estimated)["code"], "MIDSALES_ESTIMATED_FEE_ADMIN_ONLY")

        actual = upload(
            PrivateAttachment.CATEGORY_FEE_ACTUAL,
            self.provider.auth_user_id,
            admin=True,
            mobile=True,
        )
        self.assertEqual(actual.status_code, 201)
        denied_actual = upload(PrivateAttachment.CATEGORY_FEE_ACTUAL, "proof-admin", admin=True)
        self.assertEqual(denied_actual.status_code, 403)
        self.assertEqual(self.data(denied_actual)["code"], "MIDSALES_ATTACHMENT_FIELD_UPLOAD_ONLY")

    def test_completed_node_materials_are_read_only_for_provider_and_manager(self):
        self.list_proofs(self.provider.auth_user_id)
        proof = MidsalesProof.objects.get(node=self.node, proof_type=MidsalesProof.TYPE_PROCESS)
        self.node.status = ProjectNode.STATUS_COMPLETED
        self.node.save(update_fields=["status"])
        response = self.upload(
            proof,
            SimpleUploadedFile("late.jpg", b"image", content_type="image/jpeg"),
            self.provider.auth_user_id,
        )
        self.assertEqual(response.status_code, 404)
        response = self.list_proofs("proof-admin", admin=True)
        self.assertFalse(self.data(response)["canReview"])
        self.assertTrue(all(not item["canReview"] for item in self.data(response)["items"]))
        response = self.review(MidsalesProof.TYPE_PROCESS, {
            "status": MidsalesProof.STATUS_REJECTED, "opinion": "尝试更改已结束节点",
        }, "proof-admin", admin=True)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.data(response)["code"], "PROJECT_NODE_READ_ONLY")
