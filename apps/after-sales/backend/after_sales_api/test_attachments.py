from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings

from . import attachment_views, provider_self_views, views
from .models import (
    AppPermissionRule,
    FieldFeedback,
    PrivateAttachment,
    ProjectAssignment,
    ProjectNode,
    ServiceProject,
    ServiceProvider,
    ServiceResource,
    ServiceTicket,
    WorkflowCase,
)


class RequestMixin:
    factory: RequestFactory

    def authenticated(self, request, *, user_id: str, admin: bool = False, actor_id: str = ""):
        request.auth_user_id = user_id
        request.auth_user_name = user_id
        request.auth_actor_user_id = actor_id or user_id
        request.auth_actor_name = actor_id or user_id
        request.auth_is_proxy = bool(actor_id and actor_id != user_id)
        request.auth_can_use_system_admin = admin
        is_provider = ServiceProvider.objects.filter(auth_user_id=user_id).exists()
        is_provider_route = request.path in {
            "/api/after-sales/providers/me",
            "/api/after-sales/providers/apply",
        }
        request.auth_token_claims = (
            {"chn": "wechat-mini", "aud": "after-sales-mobile"}
            if not admin and (is_provider or is_provider_route)
            else {"chn": "dingtalk", "aud": "platform"}
        )
        return request

    def json_request(
        self,
        method: str,
        path: str,
        payload: dict | None,
        *,
        user_id: str,
        admin: bool = False,
    ):
        body = json.dumps(payload or {}, ensure_ascii=False)
        request_method = getattr(self.factory, method.lower())
        request = request_method(path, data=body, content_type="application/json")
        return self.authenticated(request, user_id=user_id, admin=admin)

    def upload_request(
        self,
        target_type: str,
        target_id: int,
        upload: SimpleUploadedFile,
        *,
        user_id: str,
        admin: bool = False,
        category: str = PrivateAttachment.CATEGORY_GENERAL,
        round_index: int | None = None,
        round_id: str = "",
    ):
        request = self.factory.post(
            "/api/after-sales/attachments",
            {
                "targetType": target_type,
                "targetId": str(target_id),
                "category": category,
                "file": upload,
                **({"roundIndex": str(round_index)} if round_index is not None else {}),
                **({"roundId": round_id} if round_id else {}),
            },
        )
        return self.authenticated(request, user_id=user_id, admin=admin)

    def list_request(self, target_type: str, target_id: int, *, user_id: str, admin: bool = False):
        request = self.factory.get(
            "/api/after-sales/attachments",
            {"targetType": target_type, "targetId": str(target_id)},
        )
        return self.authenticated(request, user_id=user_id, admin=admin)

    @staticmethod
    def data(response) -> dict:
        return json.loads(response.content.decode("utf-8"))


class PrivateAttachmentTests(RequestMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.media_directory = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=Path(self.media_directory.name))
        self.media_override.enable()
        AppPermissionRule.objects.all().delete()

        self.provider = ServiceProvider.objects.create(
            auth_user_id="attachment-provider",
            name="附件服务人员",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        self.other_provider = ServiceProvider.objects.create(
            auth_user_id="other-node-provider",
            name="其他节点服务人员",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        self.project = ServiceProject.objects.create(
            code="ATTACHMENT-PROJECT",
            service_type=ServiceProject.TYPE_AFTERSALES,
            name="附件权限项目",
            customer="附件测试客户",
            status=ServiceProject.STATUS_IN_PROGRESS,
        )
        self.node = ProjectNode.objects.create(
            project=self.project,
            node_key="attachment-node",
            name="附件节点",
            sequence=1,
            status=ProjectNode.STATUS_ACTIVE,
        )
        self.other_node = ProjectNode.objects.create(
            project=self.project,
            node_key="other-node",
            name="其他节点",
            sequence=2,
            status=ProjectNode.STATUS_PENDING,
        )
        ProjectAssignment.objects.create(
            project=self.project,
            node=self.node,
            provider=self.provider,
            status=ProjectAssignment.STATUS_IN_PROGRESS,
        )
        ProjectAssignment.objects.create(
            project=self.project,
            node=self.other_node,
            provider=self.other_provider,
            status=ProjectAssignment.STATUS_IN_PROGRESS,
        )

    def tearDown(self):
        self.media_override.disable()
        self.media_directory.cleanup()

    @staticmethod
    def image_file(name: str = "proof.jpg", content: bytes = b"private-image-data"):
        return SimpleUploadedFile(name, content, content_type="image/jpeg")

    def test_historical_round_attachments_are_read_only_and_latest_uploads_still_work(self):
        self.project.service_type = ServiceProject.TYPE_PRESALES
        self.project.save()
        self.node.status = ProjectNode.STATUS_ACTIVE
        self.node.save()
        response = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_PROJECT_NODE, self.node.pk, self.image_file(),
            user_id="attachment-admin", admin=True, category=PrivateAttachment.CATEGORY_SCHEME_SUBMISSION,
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        item = PrivateAttachment.objects.get(pk=self.data(response)["item"]["id"])
        self.node.business_data = {"schemeRounds": [{"attachmentIds": [str(item.id)]}, {"roundId": "latest"}]}
        self.node.save()
        response = attachment_views.attachments_collection(self.list_request(
            PrivateAttachment.TARGET_PROJECT_NODE, self.node.pk, user_id="attachment-admin", admin=True,
        ))
        self.assertFalse(self.data(response)["items"][0]["canDelete"])
        delete = self.authenticated(self.factory.delete("/"), user_id="attachment-admin", admin=True)
        response = attachment_views.attachment_item(delete, item.id)
        self.assertEqual(response.status_code, 409, self.data(response))
        self.assertTrue(PrivateAttachment.objects.filter(pk=item.pk).exists())
        self.assertTrue(item.file.storage.exists(item.file.name))
        for index, round_id in ((None, ""), (0, ""), (1, "obsolete-id")):
            response = attachment_views.attachments_collection(self.upload_request(
                PrivateAttachment.TARGET_PROJECT_NODE, self.node.pk, self.image_file(),
                user_id="attachment-admin", admin=True, category=PrivateAttachment.CATEGORY_SCHEME_SUBMISSION,
                round_index=index, round_id=round_id,
            ))
            self.assertEqual(response.status_code, 409, self.data(response))
        response = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_PROJECT_NODE, self.node.pk, self.image_file(),
            user_id="attachment-admin", admin=True, category=PrivateAttachment.CATEGORY_SCHEME_SUBMISSION,
            round_index=1, round_id="latest",
        ))
        self.assertEqual(response.status_code, 201, self.data(response))

    def test_completed_nodes_keep_downloads_but_reject_uploads_and_deletes(self):
        response = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_PROJECT_NODE, self.node.pk, self.image_file(), user_id="attachment-admin", admin=True,
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        item = PrivateAttachment.objects.get(pk=self.data(response)["item"]["id"])
        self.node.status = ProjectNode.STATUS_COMPLETED
        self.node.save()
        for service_type in (ServiceProject.TYPE_PRESALES, ServiceProject.TYPE_MIDSALES, ServiceProject.TYPE_AFTERSALES):
            with self.subTest(service_type=service_type):
                self.project.service_type = service_type
                self.project.save()
                response = attachment_views.attachments_collection(self.upload_request(
                    PrivateAttachment.TARGET_PROJECT_NODE, self.node.pk, self.image_file(), user_id="attachment-admin", admin=True,
                ))
                self.assertEqual(response.status_code, 409, self.data(response))
                request = self.authenticated(self.factory.delete("/"), user_id="attachment-admin", admin=True)
                self.assertEqual(attachment_views.attachment_item(request, item.id).status_code, 409)
                request = self.authenticated(self.factory.get("/"), user_id="attachment-admin", admin=True)
                download = attachment_views.attachment_download(request, item.id)
                self.assertEqual(download.status_code, 200)
                download.close()
                response = attachment_views.attachments_collection(self.list_request(
                    PrivateAttachment.TARGET_PROJECT_NODE, self.node.pk, user_id="attachment-admin", admin=True,
                ))
                self.assertFalse(self.data(response)["items"][0]["canDelete"])
        self.assertTrue(item.file.storage.exists(item.file.name))

    def test_attachment_ids_must_be_positive_database_integers(self):
        invalid_target_ids = (
            "device-install",
            "node-1",
            "0",
            "-1",
            "1.5",
            "true",
            str(attachment_views.MAX_DATABASE_ID + 1),
            "9" * 5000,
        )
        for target_id in invalid_target_ids:
            with self.subTest(target_id=target_id):
                response = attachment_views.attachments_collection(self.list_request(
                    PrivateAttachment.TARGET_PROJECT_NODE,
                    target_id,
                    user_id="attachment-admin",
                    admin=True,
                ))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.data(response)["code"], "INVALID_ATTACHMENT_TARGET_ID")

        upper_bound = attachment_views.attachments_collection(self.list_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            attachment_views.MAX_DATABASE_ID,
            user_id="attachment-admin",
            admin=True,
        ))
        self.assertEqual(upper_bound.status_code, 404)
        self.assertEqual(self.data(upper_bound)["code"], "ATTACHMENT_TARGET_NOT_FOUND")

        invalid_attachment_id = attachment_views.MAX_DATABASE_ID + 1
        request = self.authenticated(
            self.factory.get(f"/api/after-sales/attachments/{invalid_attachment_id}/download"),
            user_id="attachment-admin",
            admin=True,
        )
        self.assertEqual(
            attachment_views.attachment_download(request, invalid_attachment_id).status_code,
            404,
        )
        request = self.authenticated(
            self.factory.delete(f"/api/after-sales/attachments/{invalid_attachment_id}"),
            user_id="attachment-admin",
            admin=True,
        )
        self.assertEqual(
            attachment_views.attachment_item(request, invalid_attachment_id).status_code,
            404,
        )

    def test_exact_node_provider_can_upload_list_download_and_admin_delete(self):
        response = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            self.node.id,
            self.image_file(),
            user_id=self.provider.auth_user_id,
        ))
        self.assertEqual(response.status_code, 201)
        item_data = self.data(response)["item"]
        attachment = PrivateAttachment.objects.get(pk=item_data["id"])
        stored_path = Path(self.media_directory.name, attachment.file.name)
        self.assertTrue(stored_path.exists())
        self.assertNotEqual(attachment.file.name, attachment.original_name)

        response = attachment_views.attachments_collection(self.list_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            self.node.id,
            user_id=self.provider.auth_user_id,
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.data(response)["items"]), 1)
        self.assertTrue(self.data(response)["items"][0]["canDelete"])

        request = self.authenticated(
            self.factory.get(f"/api/after-sales/attachments/{attachment.id}/download"),
            user_id=self.provider.auth_user_id,
        )
        response = attachment_views.attachment_download(request, attachment.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"private-image-data")
        self.assertIn("proof.jpg", response.headers["Content-Disposition"])
        response.file_to_stream.close()

        response = attachment_views.attachments_collection(self.list_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            self.node.id,
            user_id=self.other_provider.auth_user_id,
        ))
        self.assertEqual(response.status_code, 404)
        request = self.authenticated(
            self.factory.get(f"/api/after-sales/attachments/{attachment.id}/download"),
            user_id=self.other_provider.auth_user_id,
        )
        self.assertEqual(attachment_views.attachment_download(request, attachment.id).status_code, 404)

        request = self.authenticated(
            self.factory.delete(f"/api/after-sales/attachments/{attachment.id}"),
            user_id="attachment-admin",
            admin=True,
        )
        response = attachment_views.attachment_item(request, attachment.id)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PrivateAttachment.objects.filter(pk=attachment.id).exists())
        self.assertFalse(stored_path.exists())

    def test_estimated_and_actual_fee_attachments_use_independent_categories(self):
        for category, filename in (
            (PrivateAttachment.CATEGORY_FEE_ESTIMATED, "estimated.jpg"),
            (PrivateAttachment.CATEGORY_FEE_ACTUAL, "actual.jpg"),
        ):
            response = attachment_views.attachments_collection(self.upload_request(
                PrivateAttachment.TARGET_PROJECT_NODE,
                self.node.id,
                self.image_file(filename),
                user_id=self.provider.auth_user_id,
                category=category,
            ))
            self.assertEqual(response.status_code, 201)
            self.assertEqual(self.data(response)["item"]["category"], category)

        response = attachment_views.attachments_collection(self.list_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            self.node.id,
            user_id=self.provider.auth_user_id,
        ))
        self.assertEqual(response.status_code, 200)
        items = self.data(response)["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual(
            {item["category"] for item in items},
            {
                PrivateAttachment.CATEGORY_FEE_ESTIMATED,
                PrivateAttachment.CATEGORY_FEE_ACTUAL,
            },
        )

    def test_aftersales_field_attachments_are_uploaded_by_provider_and_read_only_for_admin(self):
        self.node.node_key = "onsite-service"
        self.node.save(update_fields=["node_key"])

        uploaded = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            self.node.id,
            self.image_file("onsite.jpg"),
            user_id=self.provider.auth_user_id,
            category=PrivateAttachment.CATEGORY_INSTALLATION,
        ))
        self.assertEqual(uploaded.status_code, 201, self.data(uploaded))
        attachment_id = self.data(uploaded)["item"]["id"]

        admin_list = attachment_views.attachments_collection(self.list_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            self.node.id,
            user_id="attachment-admin",
            admin=True,
        ))
        self.assertEqual(admin_list.status_code, 200, self.data(admin_list))
        self.assertFalse(self.data(admin_list)["items"][0]["canDelete"])

        admin_upload = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            self.node.id,
            self.image_file("admin.jpg"),
            user_id="attachment-admin",
            admin=True,
            category=PrivateAttachment.CATEGORY_INSTALLATION,
        ))
        self.assertEqual(admin_upload.status_code, 403, self.data(admin_upload))

        provider_estimated = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            self.node.id,
            self.image_file("estimated.jpg"),
            user_id=self.provider.auth_user_id,
            category=PrivateAttachment.CATEGORY_FEE_ESTIMATED,
        ))
        self.assertEqual(provider_estimated.status_code, 403, self.data(provider_estimated))

        admin_delete = attachment_views.attachment_item(self.authenticated(
            self.factory.delete(f"/api/after-sales/attachments/{attachment_id}"),
            user_id="attachment-admin",
            admin=True,
        ), attachment_id)
        self.assertEqual(admin_delete.status_code, 403, self.data(admin_delete))

    def test_presales_delivery_attachment_is_management_owned(self):
        self.project.service_type = ServiceProject.TYPE_PRESALES
        self.project.save(update_fields=["service_type"])
        self.node.node_key = "early-plan"
        self.node.kind = "delivery"
        self.node.actual_start_at = datetime.fromisoformat("2026-09-03T09:00:00+00:00")
        self.node.save(update_fields=["node_key", "kind", "actual_start_at"])

        provider_upload = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            self.node.id,
            self.image_file("presales-delivery.jpg"),
            user_id=self.provider.auth_user_id,
        ))
        self.assertEqual(provider_upload.status_code, 404, self.data(provider_upload))

        admin_upload = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            self.node.id,
            self.image_file("admin-presales.jpg"),
            user_id="attachment-admin",
            admin=True,
        ))
        self.assertEqual(admin_upload.status_code, 201, self.data(admin_upload))
        attachment_id = self.data(admin_upload)["item"]["id"]
        self.assertTrue(self.data(admin_upload)["item"]["canDelete"])

        admin_list = attachment_views.attachments_collection(self.list_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            self.node.id,
            user_id="attachment-admin",
            admin=True,
        ))
        self.assertEqual(admin_list.status_code, 200, self.data(admin_list))
        self.assertTrue(all(item["canDelete"] for item in self.data(admin_list)["items"]))

        admin_delete = attachment_views.attachment_item(self.authenticated(
            self.factory.delete(f"/api/after-sales/attachments/{attachment_id}"),
            user_id="attachment-admin",
            admin=True,
        ), attachment_id)
        self.assertEqual(admin_delete.status_code, 200, self.data(admin_delete))

    def test_scheme_submission_attachment_uses_its_own_category(self):
        response = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_PROJECT_NODE,
            self.node.id,
            self.image_file("scheme.jpg"),
            user_id=self.provider.auth_user_id,
            category=PrivateAttachment.CATEGORY_SCHEME_SUBMISSION,
        ))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            self.data(response)["item"]["category"],
            PrivateAttachment.CATEGORY_SCHEME_SUBMISSION,
        )

    def test_any_file_type_can_be_uploaded_and_downloaded_without_changing_its_bytes(self):
        for name, mime_type in (
            ("方案.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
            ("工程图.DWG", "application/octet-stream"),
            ("资料.rar", "application/x-rar-compressed"),
            ("资料.7z", "application/x-7z-compressed"),
            ("设计.psd", "image/vnd.adobe.photoshop"),
            ("未知格式.custom", "application/x-custom-format"),
            ("无后缀文件", "application/octet-stream"),
            ("工具.exe", "application/x-msdownload"),
            ("页面.html", "text/html"),
            ("photo.jpg", "application/pdf"),
        ):
            with self.subTest(name=name):
                content = b"arbitrary-attachment-bytes\x00\xff"
                upload = SimpleUploadedFile(name, content, content_type=mime_type)
                response = attachment_views.attachments_collection(self.upload_request(
                    PrivateAttachment.TARGET_PROJECT_NODE, self.node.id, upload,
                    user_id=self.provider.auth_user_id,
                ))
                self.assertEqual(response.status_code, 201, self.data(response))
                item = self.data(response)["item"]
                self.assertEqual(item["originalName"], name)
                self.assertEqual(item["mimeType"], mime_type)
                request = self.authenticated(self.factory.get("/"), user_id=self.provider.auth_user_id)
                download = attachment_views.attachment_download(request, item["id"])
                self.assertEqual(download.status_code, 200)
                self.assertTrue(download["Content-Disposition"].startswith("attachment;"))
                self.assertEqual(download["X-Content-Type-Options"], "nosniff")
                self.assertEqual(b"".join(download.streaming_content), content)
                download.close()

    def test_missing_or_unusable_mime_type_uses_binary_download_type(self):
        for mime_type in (None, "", "application/" + "x" * 128, "text/html\r\nInjected: yes"):
            with self.subTest(mime_type=mime_type):
                name, content_type, failure = attachment_views._validate_upload(SimpleNamespace(
                    name="未知文件", size=10, content_type=mime_type,
                ))
                self.assertIsNone(failure)
                self.assertEqual(name, "未知文件")
                self.assertEqual(content_type, "application/octet-stream")

    def test_size_and_empty_file_limits_remain_enforced(self):
        with patch.object(attachment_views, "MAX_ATTACHMENT_SIZE", 2):
            response = attachment_views.attachments_collection(self.upload_request(
                PrivateAttachment.TARGET_PROJECT_NODE,
                self.node.id,
                self.image_file("oversized.jpg", b"xxx"),
                user_id=self.provider.auth_user_id,
            ))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.data(response)["code"], "ATTACHMENT_TOO_LARGE")
        self.assertEqual(PrivateAttachment.objects.count(), 0)
        response = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_PROJECT_NODE, self.node.id,
            SimpleUploadedFile("empty.custom", b"", content_type="application/octet-stream"),
            user_id=self.provider.auth_user_id,
        ))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.data(response)["code"], "EMPTY_ATTACHMENT")
        self.assertEqual(PrivateAttachment.objects.count(), 0)

    def test_attachment_size_boundary_is_200_mb_per_file(self):
        self.assertEqual(attachment_views.MAX_ATTACHMENT_SIZE, 200 * 1024 * 1024)
        upload = SimpleNamespace(
            name="boundary.pdf",
            content_type="application/pdf",
            size=attachment_views.MAX_ATTACHMENT_SIZE,
        )
        self.assertIsNone(attachment_views._validate_upload(upload)[2])

        upload.size += 1
        failure = attachment_views._validate_upload(upload)[2]
        self.assertEqual(failure.status_code, 400)
        self.assertEqual(self.data(failure)["code"], "ATTACHMENT_TOO_LARGE")
        self.assertIn("200MB", self.data(failure)["error"])

    def test_all_supported_targets_apply_their_own_access_rules(self):
        ticket = ServiceTicket.objects.create(
            code="ATTACHMENT-TICKET",
            project=self.project,
            node=self.node,
            title="附件工单",
            ticket_type="现场问题",
            reporter_user_id=self.provider.auth_user_id,
            description="工单附件权限测试",
        )
        feedback = FieldFeedback.objects.create(
            project=self.project,
            node=self.node,
            provider=self.provider,
            feedback_type=FieldFeedback.TYPE_ISSUE,
            content="反馈附件权限测试",
        )
        for target_type, target_id in (
            (PrivateAttachment.TARGET_TICKET, ticket.id),
            (PrivateAttachment.TARGET_FEEDBACK, feedback.id),
            (PrivateAttachment.TARGET_PROVIDER_APPLICATION, self.provider.id),
        ):
            response = attachment_views.attachments_collection(self.upload_request(
                target_type,
                target_id,
                self.image_file(f"{target_type}.jpg"),
                user_id=self.provider.auth_user_id,
            ))
            self.assertEqual(response.status_code, 201, target_type)
            response = attachment_views.attachments_collection(self.list_request(
                target_type,
                target_id,
                user_id=self.other_provider.auth_user_id,
            ))
            self.assertEqual(response.status_code, 404, target_type)

        resource = ServiceResource.objects.create(
            project=self.project,
            node_key=self.node.node_key,
            title="节点资料",
            resource_type=ServiceResource.TYPE_MANUAL,
            audience=ServiceResource.AUDIENCE_ASSIGNED,
        )
        response = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_RESOURCE,
            resource.id,
            self.image_file("resource.jpg"),
            user_id=self.provider.auth_user_id,
        ))
        self.assertEqual(response.status_code, 404)
        response = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_RESOURCE,
            resource.id,
            self.image_file("resource.jpg"),
            user_id="attachment-admin",
            admin=True,
        ))
        self.assertEqual(response.status_code, 201)
        response = attachment_views.attachments_collection(self.list_request(
            PrivateAttachment.TARGET_RESOURCE,
            resource.id,
            user_id=self.provider.auth_user_id,
        ))
        self.assertEqual(response.status_code, 200)
        response = attachment_views.attachments_collection(self.list_request(
            PrivateAttachment.TARGET_RESOURCE,
            resource.id,
            user_id=self.other_provider.auth_user_id,
        ))
        self.assertEqual(response.status_code, 404)

    def test_only_original_uploader_or_admin_can_delete(self):
        ticket = ServiceTicket.objects.create(
            code="ATTACHMENT-DELETE-TICKET",
            project=self.project,
            node=self.node,
            title="删除权限",
            ticket_type="现场问题",
            reporter_user_id=self.provider.auth_user_id,
            owner_user_id=self.other_provider.auth_user_id,
            description="删除权限测试",
        )
        response = attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_TICKET,
            ticket.id,
            self.image_file("delete.jpg"),
            user_id=self.provider.auth_user_id,
        ))
        attachment_id = self.data(response)["item"]["id"]
        request = self.authenticated(
            self.factory.delete(f"/api/after-sales/attachments/{attachment_id}"),
            user_id=self.other_provider.auth_user_id,
        )
        response = attachment_views.attachment_item(request, attachment_id)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(PrivateAttachment.objects.filter(pk=attachment_id).exists())

    def test_case_target_is_rejected_while_historical_data_is_preserved(self):
        case = WorkflowCase.objects.create(
            code="ATTACHMENT-HISTORICAL-CASE",
            case_type=WorkflowCase.TYPE_SUPPORT,
            title="历史事项附件",
            applicant_user_id=self.provider.auth_user_id,
            content="历史数据保留测试",
        )

        for request in (
            self.upload_request(
                PrivateAttachment.TARGET_CASE,
                case.id,
                self.image_file("retired-case.jpg"),
                user_id=self.provider.auth_user_id,
            ),
            self.list_request(
                PrivateAttachment.TARGET_CASE,
                case.id,
                user_id=self.provider.auth_user_id,
            ),
        ):
            with self.subTest(method=request.method):
                response = attachment_views.attachments_collection(request)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.data(response)["code"], "INVALID_ATTACHMENT_TARGET_TYPE")

        historical_attachment = PrivateAttachment.objects.create(
            target_type=PrivateAttachment.TARGET_CASE,
            target_id=case.id,
            file=self.image_file("historical-case.jpg"),
            original_name="historical-case.jpg",
            mime_type="image/jpeg",
            size=18,
            uploaded_by=self.provider.auth_user_id,
        )
        stored_name = historical_attachment.file.name
        self.assertTrue(historical_attachment.file.storage.exists(stored_name))
        for admin in (False, True):
            with self.subTest(download_as_admin=admin):
                download = self.authenticated(
                    self.factory.get(f"/api/after-sales/attachments/{historical_attachment.id}/download"),
                    user_id="attachment-admin" if admin else self.provider.auth_user_id,
                    admin=admin,
                )
                response = attachment_views.attachment_download(download, historical_attachment.id)

                self.assertEqual(response.status_code, 404)
                self.assertEqual(self.data(response)["code"], "ATTACHMENT_NOT_FOUND")

            with self.subTest(delete_as_admin=admin):
                delete = self.authenticated(
                    self.factory.delete(f"/api/after-sales/attachments/{historical_attachment.id}"),
                    user_id="attachment-admin" if admin else self.provider.auth_user_id,
                    admin=admin,
                )
                response = attachment_views.attachment_item(delete, historical_attachment.id)

                self.assertEqual(response.status_code, 404)
                self.assertEqual(self.data(response)["code"], "ATTACHMENT_NOT_FOUND")
                self.assertTrue(PrivateAttachment.objects.filter(pk=historical_attachment.id).exists())
                self.assertTrue(historical_attachment.file.storage.exists(stored_name))
        self.assertTrue(WorkflowCase.objects.filter(pk=case.id).exists())


class ProviderApplicationTests(RequestMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_new_application_requires_contact_and_city(self):
        request = self.json_request(
            "post",
            "/api/after-sales/providers/apply",
            {"name": "资料不完整人员", "role": ServiceProvider.ROLE_INSTALLER},
            user_id="incomplete-provider",
        )

        response = provider_self_views.provider_apply(request)

        self.assertEqual(response.status_code, 400, self.data(response))
        self.assertEqual(self.data(response)["code"], "INVALID_PROVIDER_APPLICATION")
        self.assertFalse(ServiceProvider.objects.filter(auth_user_id="incomplete-provider").exists())

    def test_application_is_bound_to_current_user_and_starts_pending(self):
        user_id = "new-provider-applicant"
        request = self.authenticated(
            self.factory.get("/api/after-sales/providers/me"),
            user_id=user_id,
        )
        response = provider_self_views.provider_me(request)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.data(response)["item"])

        forged = self.json_request(
            "post",
            "/api/after-sales/providers/apply",
            {"authUserId": "another-user", "name": "伪造申请"},
            user_id=user_id,
        )
        response = provider_self_views.provider_apply(forged)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ServiceProvider.objects.filter(auth_user_id=user_id).exists())
        self.assertFalse(ServiceProvider.objects.filter(auth_user_id="another-user").exists())

        request = self.json_request(
            "post",
            "/api/after-sales/providers/apply",
            {
                "authUserId": user_id,
                "name": "新申请人员",
                "role": ServiceProvider.ROLE_PARTNER,
                "phone": "13800000000",
                "city": "杭州",
                "regions": ["杭州", "宁波"],
                "skills": ["设备安装", "中控联调"],
                "bio": "项目经验说明",
                "certificationStatus": ServiceProvider.CERT_CERTIFIED,
            },
            user_id=user_id,
        )
        response = provider_self_views.provider_apply(request)
        self.assertEqual(response.status_code, 201)
        provider = ServiceProvider.objects.get(auth_user_id=user_id)
        self.assertEqual(provider.certification_status, ServiceProvider.CERT_PENDING)
        self.assertEqual(provider.created_by, user_id)
        self.assertEqual(provider.regions, ["杭州", "宁波"])

    def test_reapplication_preserves_metrics_resets_review_and_admin_can_certify(self):
        provider = ServiceProvider.objects.create(
            auth_user_id="certified-applicant",
            name="原服务人员",
            certification_status=ServiceProvider.CERT_CERTIFIED,
            score="4.80",
            month_orders=7,
            total_orders=31,
        )
        request = self.json_request(
            "patch",
            "/api/after-sales/providers/apply",
            {
                "authUserId": provider.auth_user_id,
                "name": "更新后的服务人员",
                "city": "宁波",
                "certificationStatus": ServiceProvider.CERT_CERTIFIED,
                "score": "5.00",
                "monthOrders": 999,
                "totalOrders": 999,
            },
            user_id=provider.auth_user_id,
        )
        response = provider_self_views.provider_apply(request)
        self.assertEqual(response.status_code, 200)
        provider.refresh_from_db()
        self.assertEqual(provider.name, "更新后的服务人员")
        self.assertEqual(provider.city, "宁波")
        self.assertEqual(provider.certification_status, ServiceProvider.CERT_PENDING)
        self.assertEqual(str(provider.score), "4.80")
        self.assertEqual(provider.month_orders, 7)
        self.assertEqual(provider.total_orders, 31)

        request = self.json_request(
            "patch",
            f"/api/after-sales/providers/{provider.id}",
            {"certificationStatus": ServiceProvider.CERT_CERTIFIED},
            user_id="provider-review-admin",
            admin=True,
        )
        response = views.provider_item(request, provider.id)
        self.assertEqual(response.status_code, 200)
        provider.refresh_from_db()
        self.assertEqual(provider.certification_status, ServiceProvider.CERT_CERTIFIED)
