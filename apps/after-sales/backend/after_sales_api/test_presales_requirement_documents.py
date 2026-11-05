from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from . import attachment_views
from .models import AppPermissionRule, PrivateAttachment, ProjectNode, ServiceProject, ServiceProvider
from .services import DomainValidationError
from .test_attachments import RequestMixin


class PresalesRequirementDocumentsTests(RequestMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        media_settings = override_settings(MEDIA_ROOT=Path(media.name))
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        cache.clear()
        self.addCleanup(cache.clear)
        AppPermissionRule.objects.all().delete()
        AppPermissionRule.objects.create(permission="sales", scope_type="employee", target_id="sales-user")
        self.project = ServiceProject.objects.create(
            code="PS-DOCS", name="项目需求文档验证", service_type="presales", status="in_progress",
        )
        self.early = ProjectNode.objects.create(
            project=self.project, node_key="early-approval", name="前期立项", sequence=1, status="completed",
        )

    def upload(self, *, user="sales-user", category="general", project=None):
        return attachment_views.attachments_collection(self.upload_request(
            PrivateAttachment.TARGET_PRESALES_PROJECT, (project or self.project).pk,
            SimpleUploadedFile("项目需求.pdf", b"requirement-pdf", content_type="application/pdf"),
            user_id=user, category=category,
        ))

    def item(self, **values):
        return PrivateAttachment.objects.create(
            target_type=values.pop("target_type", PrivateAttachment.TARGET_PRESALES_PROJECT),
            target_id=values.pop("target_id", self.project.pk),
            category=values.pop("category", "general"), original_name="原始需求.pdf",
            mime_type="application/pdf", size=12, uploaded_by="sales-user", file="test-not-stored.pdf", **values,
        )

    def request(self, method="get", *, user="sales-user"):
        return self.authenticated(getattr(self.factory, method)("/"), user_id=user)

    def test_upload_download_delete_are_project_scoped_even_after_early_node_completed(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, self.data(response))
        item = PrivateAttachment.objects.get(pk=self.data(response)["item"]["id"])
        self.assertEqual((item.target_type, item.target_id), (PrivateAttachment.TARGET_PRESALES_PROJECT, self.project.pk))
        self.assertTrue(self.data(response)["item"]["canDelete"])
        response = attachment_views.attachment_download(self.request(), item.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"requirement-pdf")
        response.close()
        response = attachment_views.attachment_item(self.request("delete"), item.pk)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertFalse(PrivateAttachment.objects.filter(pk=item.pk).exists())
        self.assertFalse(item.file.storage.exists(item.file.name))

    def test_lists_originals_with_project_documents_without_reclassifying_historical_files(self):
        legacy = self.item(target_type="project_node", target_id=self.early.pk)
        new = self.item()
        self.item(target_type="project_node", target_id=self.early.pk, category="fee_estimated")
        self.item(category="scheme_submission")
        other_node = ProjectNode.objects.create(project=self.project, node_key="early-plan", sequence=2)
        self.item(target_type="project_node", target_id=other_node.pk)
        other_project = ServiceProject.objects.create(code="PS-DOCS-OTHER", service_type="presales")
        self.item(target_id=other_project.pk)
        response = attachment_views.attachments_collection(self.list_request(
            "presales_project", self.project.pk, user_id="sales-user",
        ))
        rows = {row["id"]: row for row in self.data(response)["items"]}
        self.assertEqual(set(rows), {legacy.pk, new.pk})
        self.assertFalse(rows[legacy.pk]["canDelete"])
        self.assertTrue(rows[new.pk]["canDelete"])
        self.assertEqual(rows[legacy.pk]["targetType"], "project_node")
        denied = attachment_views.attachment_item(self.request("delete"), legacy.pk)
        self.assertEqual(denied.status_code, 409)
        self.assertTrue(PrivateAttachment.objects.filter(pk=legacy.pk).exists())

    def test_crm_scope_is_rechecked_for_list_upload_download_and_delete(self):
        self.project.source_crm_id = "private-crm"
        self.project.save(update_fields=["source_crm_id"])
        item = self.item()
        failure = DomainValidationError("无 CRM 项目权限", code="CRM_PERMISSION_DENIED", status=403)
        with patch.object(attachment_views, "assert_crm_project_access", side_effect=failure) as check:
            response = attachment_views.attachments_collection(self.list_request(
                "presales_project", self.project.pk, user_id="sales-user",
            ))
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.upload().status_code, 403)
            self.assertEqual(attachment_views.attachment_download(self.request(), item.pk).status_code, 404)
            self.assertEqual(attachment_views.attachment_item(self.request("delete"), item.pk).status_code, 404)
            self.assertEqual([call.kwargs["write"] for call in check.call_args_list], [False, True, False, True])
        self.assertTrue(PrivateAttachment.objects.filter(pk=item.pk).exists())

    def test_ungranted_and_wechat_users_cannot_read_or_write_project_documents(self):
        item = self.item()
        ServiceProvider.objects.create(auth_user_id="wx-worker", name="现场人员", certification_status="certified")
        for user in ("ungranted", "wx-worker"):
            with self.subTest(user=user):
                self.assertIn(self.upload(user=user).status_code, {403, 404})
                response = attachment_views.attachments_collection(self.list_request(
                    "presales_project", self.project.pk, user_id=user,
                ))
                self.assertIn(response.status_code, {403, 404})
                self.assertEqual(attachment_views.attachment_download(self.request(user=user), item.pk).status_code, 404)
                self.assertEqual(attachment_views.attachment_item(self.request("delete", user=user), item.pk).status_code, 404)

    def test_only_presales_general_files_are_accepted_and_deleted_projects_are_read_only(self):
        self.assertEqual(self.upload(category="fee_estimated").status_code, 400)
        for service_type in ("midsales", "aftersales"):
            other = ServiceProject.objects.create(code=f"DOC-{service_type}", service_type=service_type)
            self.assertEqual(self.upload(project=other).status_code, 403)
        item = self.item()
        self.project.deleted_at = timezone.now()
        self.project.save(update_fields=["deleted_at"])
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(attachment_views.attachment_item(self.request("delete"), item.pk).status_code, 409)
        response = attachment_views.attachments_collection(self.list_request(
            "presales_project", self.project.pk, user_id="sales-user",
        ))
        self.assertFalse(self.data(response)["items"][0]["canDelete"])

    def test_completed_project_documents_follow_project_metadata_permissions_and_keep_proxy_actor(self):
        self.project.status = "completed"
        self.project.save(update_fields=["status"])
        request = self.upload_request(
            "presales_project", self.project.pk, SimpleUploadedFile("需求.bin", b"contents"), user_id="sales-user",
        )
        self.authenticated(request, user_id="sales-user", actor_id="proxy-admin")
        response = attachment_views.attachments_collection(request)
        self.assertEqual(response.status_code, 201, self.data(response))
        self.assertEqual(self.data(response)["item"]["uploadedActorId"], "proxy-admin")
        self.assertTrue(self.data(response)["item"]["canDelete"])
