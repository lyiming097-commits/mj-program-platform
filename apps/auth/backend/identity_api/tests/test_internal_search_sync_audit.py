import json
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from django.test import TestCase

from identity_api.auth.session import create_auth_session_token
from identity_api.auth.tokens import AUTH_COOKIE_NAME
from identity_api.models import Department, DepartmentEmployee, Employee, InternalServiceCredential, OrganizationState, OrganizationSyncRun, PlatformEnabledDepartment


INTERNAL_SECRET = "test-internal-secret-0123456789abcdef"


class InternalSearchAndSyncTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_SEC_FETCH_SITE"] = "same-origin"
        self.admin = Employee.objects.create(user_id="admin", name="江颂扬")
        department = Department.objects.create(dept_id=1, name="商务部门")
        DepartmentEmployee.objects.create(department=department, employee=self.admin)
        PlatformEnabledDepartment.objects.create(department=department, enabled_by=self.admin.user_id)
        credential = InternalServiceCredential(service_name="test-service", app_id="test")
        credential.set_secret(INTERNAL_SECRET)
        credential.save()

    def authenticate_admin(self):
        token = create_auth_session_token(self.admin)["token"]
        self.client.cookies[AUTH_COOKIE_NAME] = token

    def internal_post(self, path, payload):
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_INTERNAL_SERVICE="test-service",
            HTTP_X_INTERNAL_AUTH_SECRET=INTERNAL_SECRET,
        )

    def test_internal_user_and_department_search_support_pinyin(self):
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.internal_post("/api/internal/org/users/search", {"keyword": "jsy"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["userId"], self.admin.user_id)
        self.assertTrue(response.json()["items"][0]["isSystemAdmin"])
        self.assertEqual(response.json()["items"][0]["pinyin"], "jiangsongyang")
        self.assertEqual(response.json()["items"][0]["pinyinInitials"], "jsy")

        response = self.internal_post("/api/internal/org/users/search", {"keyword": "jiang song yang"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["userId"], self.admin.user_id)

        response = self.internal_post("/api/internal/org/departments/search", {"keyword": "swbm"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["deptId"], 1)

    def test_administrative_region_search_supports_code_name_and_pinyin(self):
        self.authenticate_admin()
        response = self.client.get(
            "/api/directory/administrative-regions/search",
            {"keyword": "yuhangqu"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["code"], "330110")
        self.assertEqual(response.json()["items"][0]["pinyinInitials"], "yhq")

        response = self.internal_post(
            "/api/internal/directory/administrative-regions/search",
            {"keyword": "330100"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["name"], "杭州市")

    def test_sync_request_is_enqueued_and_returns_202(self):
        self.authenticate_admin()
        task_result = Mock(id="task-123")
        with (
            patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}),
            patch("identity_api.org.views.sync_organization_contacts_task.delay", return_value=task_result),
        ):
            response = self.client.post("/api/dingtalk/sync_contacts", content_type="application/json")
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["accepted"])
        self.assertEqual(OrganizationSyncRun.objects.count(), 1)

    def test_sync_status_reports_last_successful_data_update(self):
        self.authenticate_admin()
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.get("/api/dingtalk/sync_contacts/status")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["lastSyncedAt"], "")

            last_synced_at = datetime(2026, 9, 21, 2, 30, tzinfo=timezone.utc)
            OrganizationState.objects.filter(state_id=1).update(revision=1, synced_at=last_synced_at)
            OrganizationSyncRun.objects.create(status=OrganizationSyncRun.STATUS_FAILED, error="钉钉请求失败")
            response = self.client.get("/api/dingtalk/sync_contacts/status")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["syncRun"]["status"], OrganizationSyncRun.STATUS_FAILED)
            self.assertEqual(response.json()["lastSyncedAt"], last_synced_at.isoformat())

    def test_sync_status_does_not_expose_last_sync_to_non_admins(self):
        OrganizationState.objects.filter(state_id=1).update(
            synced_at=datetime(2026, 9, 21, 2, 30, tzinfo=timezone.utc)
        )
        self.authenticate_admin()
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", set()):
            response = self.client.get("/api/dingtalk/sync_contacts/status")
        self.assertEqual(response.status_code, 403)

    def test_removed_operation_audit_endpoint_returns_404(self):
        self.authenticate_admin()
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.get("/api/auth/audit/events")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "NOT_FOUND")
