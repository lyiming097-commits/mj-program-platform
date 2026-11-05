import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from . import action_views, draft_views, permission_views, settings_views, submission_views
from .draft_views import save_draft
from .models import (
    CollectionDraft,
    OrganizationDepartment,
    OrganizationDepartmentEmployee,
    OrganizationEmployee,
    OrganizationSyncState,
    PermissionCode,
    PermissionRule,
    PermissionScope,
    Submission,
    SubmissionAttachment,
    SubmissionStatus,
)
from .platform import SameOriginWriteMiddleware
from .permissions import resolve_permission_access
from .org_sync import refresh_organization_snapshot
from .submission_views import add_attachment, attachment_detail, create_submission, submission_detail
from .urls import competitor_root


class AppPlatformTests(TestCase):
    def test_health_endpoints_are_public(self):
        for path in (
            "/api/health/",
            "/api/health/live",
            "/api/health/ready",
            "/api/competitive/health/",
            "/api/competitive/health/live",
            "/api/competitive/health/ready",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["ok"])

    def test_readiness_reports_database_failure(self):
        for path in ("/api/health/ready", "/api/competitive/health/ready"):
            with self.subTest(path=path):
                with patch(
                    "competitive_vue_api.views.connection.cursor",
                    side_effect=RuntimeError("database unavailable"),
                ):
                    response = self.client.get(path)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["code"], "DATABASE_UNAVAILABLE")

    def test_app_health_public_paths_are_exact(self):
        response = self.client.get("/api/competitive/health/ready/extra")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "MISSING_AUTH_TOKEN")

    def test_cross_origin_write_is_blocked(self):
        middleware = SameOriginWriteMiddleware(lambda _request: JsonResponse({"ok": True}))
        request = RequestFactory().post(
            "/api/competitive/session/",
            HTTP_HOST="platform.example.test",
            HTTP_ORIGIN="https://other.example.test",
            HTTP_SEC_FETCH_SITE="cross-site",
        )
        response = middleware(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["code"], "CROSS_ORIGIN_WRITE_BLOCKED")

    @override_settings(CSRF_TRUSTED_ORIGINS=["https://oa.hzmaijie.com:4433"])
    def test_configured_public_origin_write_is_allowed(self):
        middleware = SameOriginWriteMiddleware(lambda _request: JsonResponse({"ok": True}))
        request = RequestFactory().post(
            "/api/competitive/submissions",
            HTTP_HOST="oa.hzmaijie.com",
            HTTP_ORIGIN="https://oa.hzmaijie.com:4433",
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_SEC_FETCH_SITE="same-origin",
        )
        response = middleware(request)
        self.assertEqual(response.status_code, 200)

    def test_browser_write_views_delegate_csrf_to_same_origin_middleware(self):
        write_views = (
            action_views.soft_delete_competitor,
            action_views.update_competitor,
            action_views.extend_expiry,
            action_views.return_submission,
            action_views.resubmit_submission,
            action_views.create_competitor,
            action_views.merge_submission,
            draft_views.save_draft,
            draft_views.delete_draft,
            permission_views.permissions_collection,
            settings_views.setting_items,
            settings_views.setting_item_detail,
            submission_views.submission_detail,
            submission_views.submissions_root,
            submission_views.create_submission,
            submission_views.add_attachment,
            submission_views.attachment_detail,
            competitor_root,
        )

        for view in write_views:
            with self.subTest(view=view.__name__):
                self.assertTrue(getattr(view, "csrf_exempt", False))


class PermissionResolutionTests(TestCase):
    @staticmethod
    def request(user_id="user-1", system_admin=False):
        return SimpleNamespace(
            auth_user_id=user_id,
            auth_can_use_system_admin=system_admin,
        )

    def test_system_admin_receives_admin_without_org_lookup(self):
        access = resolve_permission_access(self.request(system_admin=True))

        self.assertEqual(access.permissions, frozenset({PermissionCode.ADMIN}))
        self.assertTrue(access.can_collect)
        self.assertTrue(access.can_review)
        self.assertTrue(access.can_manage)

    def test_direct_employee_rule_grants_collector(self):
        PermissionRule.objects.create(
            permission=PermissionCode.COLLECTOR,
            scope_type=PermissionScope.EMPLOYEE,
            target_id="user-1",
        )

        access = resolve_permission_access(self.request())

        self.assertEqual(access.permissions, frozenset({PermissionCode.COLLECTOR}))
        self.assertTrue(access.can_collect)
        self.assertFalse(access.can_review)

    def test_department_subtree_rule_grants_reviewer(self):
        root = OrganizationDepartment.objects.create(dept_id=1, name="总部")
        child = OrganizationDepartment.objects.create(
            dept_id=2,
            name="子部门",
            parent_dept_id=root.dept_id,
        )
        employee = OrganizationEmployee.objects.create(user_id="user-1", name="用户")
        OrganizationDepartmentEmployee.objects.create(
            department=child,
            employee=employee,
        )
        PermissionRule.objects.create(
            permission=PermissionCode.REVIEWER,
            scope_type=PermissionScope.DEPARTMENT_WITH_SUB,
            target_id=str(root.dept_id),
        )

        access = resolve_permission_access(self.request())

        self.assertEqual(access.permissions, frozenset({PermissionCode.REVIEWER}))
        self.assertTrue(access.can_review)

    def test_excluded_employee_overrides_other_sources_for_same_permission(self):
        department = OrganizationDepartment.objects.create(dept_id=3, name="销售部")
        employee = OrganizationEmployee.objects.create(user_id="user-1", name="用户")
        OrganizationDepartmentEmployee.objects.create(
            department=department,
            employee=employee,
        )
        PermissionRule.objects.bulk_create(
            [
                PermissionRule(
                    permission=PermissionCode.COLLECTOR,
                    scope_type=PermissionScope.DEPARTMENT,
                    target_id=str(department.dept_id),
                ),
                PermissionRule(
                    permission=PermissionCode.COLLECTOR,
                    scope_type=PermissionScope.EMPLOYEE,
                    target_id="user-1",
                ),
                PermissionRule(
                    permission=PermissionCode.COLLECTOR,
                    scope_type=PermissionScope.EXCLUDED_EMPLOYEE,
                    target_id="user-1",
                ),
                PermissionRule(
                    permission=PermissionCode.REVIEWER,
                    scope_type=PermissionScope.EMPLOYEE,
                    target_id="user-1",
                ),
            ]
        )

        access = resolve_permission_access(self.request())

        self.assertEqual(access.permissions, frozenset({PermissionCode.REVIEWER}))


class OrganizationSnapshotTests(TestCase):
    @patch("competitive_vue_api.org_sync.get_organization_snapshot")
    def test_recent_snapshot_skips_auth_lookup(self, get_snapshot):
        OrganizationSyncState.objects.create(
            state_key="auth-organization",
            org_revision=7,
            synced_at=timezone.now(),
        )

        result = refresh_organization_snapshot()

        self.assertFalse(result["refreshed"])
        self.assertEqual(result["orgRevision"], 7)
        get_snapshot.assert_not_called()

    @patch("competitive_vue_api.org_sync.get_organization_snapshot")
    def test_snapshot_materializes_department_membership(self, get_snapshot):
        get_snapshot.return_value = (
            [
                {"deptId": 1, "name": "总部", "parentDeptId": None},
                {"deptId": 2, "name": "销售部", "parentDeptId": 1},
            ],
            [
                {
                    "userId": "user-1",
                    "name": "用户",
                    "status": "在职",
                    "accountStatus": "启用",
                    "departments": [{"deptId": 2, "name": "销售部"}],
                }
            ],
            8,
        )

        result = refresh_organization_snapshot(force=True)

        self.assertTrue(result["refreshed"])
        self.assertEqual(result["orgRevision"], 8)
        self.assertTrue(
            OrganizationDepartmentEmployee.objects.filter(
                department_id=2,
                employee_id="user-1",
            ).exists()
        )


class SubmissionApiContractTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.reviewer_access = SimpleNamespace(can_review=True)
        self.collector_access = SimpleNamespace(can_review=False)
        self.submission = Submission.objects.create(
            product_id="product-1",
            owner="业务员",
            owner_user_id="collector-1",
            brand="竞品品牌",
            name="竞品名称",
            model="M1",
            price="1000",
            region="华东",
            location="旧地点",
            validity="一年",
            expires_on=date.today() + timedelta(days=365),
            reminder_owner="本人",
            submitted_on=date.today(),
            status=SubmissionStatus.PENDING,
        )

    @staticmethod
    def authenticate(request, user_id="reviewer-1", name="审核员"):
        request.auth_user_id = user_id
        request.auth_user_name = name
        request.auth_actor_name = name
        return request

    @patch("competitive_vue_api.domain.require_catalog_product", return_value={"id": "product-1"})
    @patch("competitive_vue_api.submission_views.request_access")
    def test_reviewer_can_save_amap_location(self, request_access, _product):
        request_access.return_value = (self.reviewer_access, None)
        payload = {
            "productId": "product-1",
            "location": "杭州市西湖区文三路",
            "located": True,
            "latitude": 30.2741,
            "longitude": 120.1551,
            "locationAccuracy": 18,
            "locatedAt": "2026-08-04T10:00:00+08:00",
            "locationSource": "device",
        }
        request = self.authenticate(
            self.factory.patch(
                f"/submissions/{self.submission.id}",
                data=json.dumps(payload),
                content_type="application/json",
            )
        )

        response = submission_detail(request, self.submission.id)

        self.assertEqual(response.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.location, payload["location"])
        self.assertEqual(self.submission.location_source, "device")
        self.assertAlmostEqual(self.submission.latitude, payload["latitude"])
        self.assertAlmostEqual(self.submission.longitude, payload["longitude"])

    @patch("competitive_vue_api.submission_views.request_access")
    def test_expired_submission_cannot_be_patched(self, request_access):
        request_access.return_value = (self.reviewer_access, None)
        self.submission.status = SubmissionStatus.EXPIRED
        self.submission.save(update_fields=["status"])
        request = self.authenticate(
            self.factory.patch(
                f"/submissions/{self.submission.id}",
                data=json.dumps({"note": "不应保存"}),
                content_type="application/json",
            )
        )

        response = submission_detail(request, self.submission.id)

        self.assertEqual(response.status_code, 409)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.note, "")

    @patch("competitive_vue_api.submission_views.delete_stored_file")
    @patch("competitive_vue_api.submission_views.save_upload")
    @patch("competitive_vue_api.submission_views.request_access")
    def test_expired_submission_rejects_attachment_upload(
        self,
        request_access,
        save_upload,
        delete_stored_file,
    ):
        request_access.return_value = (self.reviewer_access, None)
        self.submission.status = SubmissionStatus.EXPIRED
        self.submission.save(update_fields=["status"])
        save_upload.return_value = SimpleNamespace(
            original_name="参数.pdf",
            size=12,
            content_type="application/pdf",
            storage_key="submissions/expired.pdf",
        )
        upload = SimpleUploadedFile("参数.pdf", b"test", content_type="application/pdf")
        request = self.authenticate(
            self.factory.post(
                f"/submissions/{self.submission.id}/attachments",
                data={"file": upload, "category": "技术参数"},
            )
        )

        response = add_attachment(request, self.submission.id)

        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.submission.attachments.exists())
        delete_stored_file.assert_called_once_with("submissions/expired.pdf")

    @patch("competitive_vue_api.submission_views.save_upload")
    @patch("competitive_vue_api.submission_views.request_access")
    def test_reviewer_can_add_and_delete_attachment(self, request_access, save_upload):
        request_access.return_value = (self.reviewer_access, None)
        save_upload.return_value = SimpleNamespace(
            original_name="参数.pdf",
            size=12,
            content_type="application/pdf",
            storage_key="submissions/test.pdf",
        )
        upload = SimpleUploadedFile("参数.pdf", b"test content", content_type="application/pdf")
        add_request = self.authenticate(
            self.factory.post(
                f"/submissions/{self.submission.id}/attachments",
                data={"file": upload, "category": "技术参数"},
            )
        )

        add_response = add_attachment(add_request, self.submission.id)

        self.assertEqual(add_response.status_code, 201)
        attachment = SubmissionAttachment.objects.get(submission=self.submission)
        self.assertEqual(attachment.category, "技术参数")

        delete_request = self.authenticate(
            self.factory.delete(
                f"/submissions/{self.submission.id}/attachments/{attachment.id}"
            )
        )
        delete_response = attachment_detail(
            delete_request,
            self.submission.id,
            attachment.id,
        )

        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(SubmissionAttachment.objects.filter(id=attachment.id).exists())

    @patch("competitive_vue_api.submission_views.require_catalog_product", return_value={"id": "product-1"})
    @patch("competitive_vue_api.draft_views.save_upload")
    @patch("competitive_vue_api.submission_views.request_access")
    @patch("competitive_vue_api.draft_views.request_access")
    def test_draft_attachment_moves_to_submission(
        self,
        draft_access,
        submission_access,
        save_upload,
        _product,
    ):
        draft_access.return_value = (self.collector_access, None)
        submission_access.return_value = (self.collector_access, None)
        save_upload.return_value = SimpleNamespace(
            original_name="现场照片.jpg",
            size=8,
            content_type="image/jpeg",
            storage_key="drafts/photo.jpg",
        )
        draft_payload = {
            "productId": "product-1",
            "brand": "新竞品",
            "name": "桌子",
            "model": "",
            "price": "",
            "region": "华东 / 杭州",
            "location": "杭州市西湖区",
            "validity": "一年",
            "reminderOwner": "本人",
            "categories": ["产品图片"],
        }
        upload = SimpleUploadedFile("现场照片.jpg", b"jpegdata", content_type="image/jpeg")
        draft_request = self.authenticate(
            self.factory.post(
                "/drafts",
                data={"payload": json.dumps(draft_payload), "files": upload},
            ),
            user_id="collector-1",
            name="业务员",
        )
        draft_response = save_draft(draft_request)
        self.assertEqual(draft_response.status_code, 201)
        draft_id = json.loads(draft_response.content)["id"]

        submit_payload = {
            **draft_payload,
            "model": "型号待补充",
            "price": "待采集",
            "categories": [],
            "draftId": draft_id,
        }
        submit_request = self.authenticate(
            self.factory.post(
                "/submissions",
                data={"payload": json.dumps(submit_payload)},
            ),
            user_id="collector-1",
            name="业务员",
        )
        submit_response = create_submission(submit_request)

        self.assertEqual(submit_response.status_code, 201)
        created = Submission.objects.exclude(id=self.submission.id).get()
        attachment = created.attachments.get()
        self.assertEqual(attachment.filename, "现场照片.jpg")
        self.assertEqual(attachment.storage_key, "drafts/photo.jpg")
        self.assertFalse(CollectionDraft.objects.filter(id=draft_id).exists())


class SubmissionSearchTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.review_access = SimpleNamespace(can_review=True)
        self.submission = Submission.objects.create(
            product_id="product-42",
            owner="张三",
            brand="竞品品牌",
            name="竞品名称",
            model="M1",
            region="华东",
            city="杭州市",
            validity="一年",
            expires_on=date.today() + timedelta(days=30),
            reminder_owner="本人",
            submitted_on=date.today(),
            status=SubmissionStatus.PENDING,
        )

    @patch("competitive_vue_api.submission_views.request_access")
    @patch("competitive_vue_api.submission_views.get_products")
    def test_search_matches_owner_region_and_catalog_product(self, get_products, request_access):
        request_access.return_value = (self.review_access, None)
        get_products.return_value = [
            {"id": "product-42", "name": "录播主机", "model": "MJ-42"},
        ]

        for keyword in ("张三", "杭州", "录播主机"):
            with self.subTest(keyword=keyword):
                response = submission_views.submissions_collection(
                    self.factory.get("/submissions", {"q": keyword})
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(json.loads(response.content)["total"], 1)

    @patch("competitive_vue_api.submission_views.request_access")
    @patch("competitive_vue_api.submission_views.get_products", return_value=[])
    def test_search_keeps_direct_product_id_match_when_catalog_is_empty(
        self, _get_products, request_access
    ):
        request_access.return_value = (self.review_access, None)

        response = submission_views.submissions_collection(
            self.factory.get("/submissions", {"q": "product-42"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["total"], 1)
