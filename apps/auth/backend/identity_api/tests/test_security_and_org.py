import json
import threading
import time
from unittest.mock import patch

from django.db import close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.core.cache import cache

from identity_api.dingtalk.client import DingTalkAPIError
from identity_api.auth.session import create_auth_session_token
from identity_api.auth.tokens import AUTH_COOKIE_NAME, decode_auth_token
from identity_api.models import (
    Department,
    DepartmentEmployee,
    DepartmentManager,
    Employee,
    InternalServiceCredential,
    OrganizationPermissionState,
    OrganizationState,
    PlatformEnabledDepartment,
)
from identity_api.tasks import SYNC_SCHEDULER_HEARTBEAT_KEY, SYNC_WORKER_HEARTBEAT_KEY
from identity_api.org.revision import advance_organization_revision, lock_organization_state


INTERNAL_SECRET = "test-internal-secret-0123456789abcdef"


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class AuthOrganizationSecurityTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_SEC_FETCH_SITE"] = "same-origin"
        self.active = Employee.objects.create(user_id="user-active", name="普通员工")
        self.inactive = Employee.objects.create(
            user_id="user-inactive",
            name="离职员工",
            status=Employee.STATUS_INACTIVE,
            account_status=Employee.ACCOUNT_DISABLED,
        )
        self.admin = Employee.objects.create(user_id="admin", name="平台管理员")
        credential = InternalServiceCredential(service_name="crm-backend", app_id="crm")
        credential.set_secret(INTERNAL_SECRET)
        credential.save()

    def authenticate(self, employee, *, session_started_at=None):
        payload = create_auth_session_token(employee, session_started_at=session_started_at)
        self.client.cookies[AUTH_COOKIE_NAME] = payload["token"]
        return payload

    def test_regular_employee_cannot_read_inactive_employees(self):
        self.authenticate(self.active)
        response = self.client.get("/api/org/employees", {"status": "离职", "includeDepartments": 1})
        self.assertEqual(response.status_code, 403)

        response = self.client.get(f"/api/org/employees/{self.inactive.user_id}")
        self.assertEqual(response.status_code, 403)

        response = self.client.get("/api/org/employees")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["orgRevision"], 0)
        self.assertEqual({item["userId"] for item in response.json()["items"]}, {"user-active", "admin"})

    def test_only_session_validation_refreshes_auth_cookie(self):
        self.authenticate(self.active)

        organization_response = self.client.get("/api/org/employees")
        self.assertEqual(organization_response.status_code, 200)
        self.assertNotIn(AUTH_COOKIE_NAME, organization_response.cookies)

        validation_response = self.client.get("/api/auth/session/validate")
        self.assertEqual(validation_response.status_code, 200)
        self.assertIn(AUTH_COOKIE_NAME, validation_response.cookies)

    def test_disabled_regular_employee_token_is_rejected(self):
        disabled_employee = Employee.objects.create(
            user_id="disabled-regular",
            name="禁用普通员工",
            account_status=Employee.ACCOUNT_DISABLED,
        )
        self.authenticate(disabled_employee)

        response = self.client.get("/api/auth/session/validate")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "ACCOUNT_DISABLED")
        self.assertNotIn(AUTH_COOKIE_NAME, response.cookies)

    @patch("identity_api.auth.views.login_with_scan_code")
    def test_disabled_system_admin_can_login_and_introspect(self, login_mock):
        self.admin.account_status = Employee.ACCOUNT_DISABLED
        self.admin.save(update_fields=["account_status"])
        login_mock.return_value = {
            "userId": self.admin.user_id,
            "name": self.admin.name,
            "avatarUrl": "",
        }

        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            login_response = self.client.post(
                "/api/auth/code",
                data=json.dumps({"authCode": "valid-code"}),
                content_type="application/json",
            )
            self.assertEqual(login_response.status_code, 200, login_response.content)
            self.assertTrue(login_response.json()["canUseSystemAdmin"])
            self.assertEqual(login_response.json()["accountStatus"], Employee.ACCOUNT_DISABLED)
            token = login_response.cookies[AUTH_COOKIE_NAME].value

            validation_response = self.client.get("/api/auth/session/validate")
            self.assertEqual(validation_response.status_code, 200, validation_response.content)
            self.assertTrue(validation_response.json()["canUseSystemAdmin"])

            introspect_response = self.client.post(
                "/api/internal/auth/introspect",
                data=json.dumps({"token": token}),
                content_type="application/json",
                HTTP_X_INTERNAL_SERVICE="crm-backend",
                HTTP_X_INTERNAL_AUTH_SECRET=INTERNAL_SECRET,
            )

        self.assertEqual(introspect_response.status_code, 200, introspect_response.content)
        self.assertTrue(introspect_response.json()["canUseSystemAdmin"])
        self.assertEqual(introspect_response.json()["accountStatus"], Employee.ACCOUNT_DISABLED)

    def test_admin_can_read_inactive_employees(self):
        self.authenticate(self.admin)
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.get("/api/org/employees", {"status": "inactive"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["userId"] for item in response.json()["items"]], [self.inactive.user_id])

    def test_former_organization_only_appears_in_protected_inactive_list(self):
        self.inactive.former_dingtalk_departments = [{"deptId": 10, "pathText": "公司 / 销售"}]
        self.inactive.former_organization_recorded_at = self.inactive.updated_at
        self.inactive.save()

        self.authenticate(self.active)
        self.assertEqual(self.client.get("/api/org/employees/inactive").status_code, 403)
        self.authenticate(self.admin)
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.get("/api/org/employees/inactive")
            general_response = self.client.get("/api/org/employees", {"status": "inactive"})
        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertEqual(item["formerDingTalkDepartments"][0]["pathText"], "公司 / 销售")
        self.assertTrue(item["formerOrganizationRecordedAt"])
        self.assertNotIn("formerDingTalkDepartments", general_response.json()["items"][0])

    def test_regular_employee_cannot_read_inactive_department_manager(self):
        department = Department.objects.create(
            dept_id=200,
            name="历史部门",
            manager_user_id=self.inactive.user_id,
        )
        self.authenticate(self.active)

        response = self.client.get(f"/api/org/departments/{department.dept_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["manager"])

        response = self.client.get(f"/api/org/departments/{department.dept_id}/manager")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["manager"])

    def test_handover_and_account_status_reject_inconsistent_state(self):
        self.authenticate(self.admin)
        headers = {"content_type": "application/json"}
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.post(
                f"/api/org/employees/{self.active.user_id}/handover",
                data=json.dumps({"handoverUserId": self.admin.user_id}),
                **headers,
            )
            self.assertEqual(response.status_code, 400)

            response = self.client.post(
                f"/api/org/employees/{self.inactive.user_id}/account-status",
                data=json.dumps({"accountStatus": Employee.ACCOUNT_ENABLED}),
                **headers,
            )
            self.assertEqual(response.status_code, 400)

    def test_proxy_start_and_stop_keep_original_session_start(self):
        original_start = int(time.time()) - 60
        original_payload = self.authenticate(self.admin, session_started_at=original_start)
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.post(
                "/api/auth/proxy/start",
                data=json.dumps({"userId": self.active.user_id}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            proxy_claims = decode_auth_token(response.cookies[AUTH_COOKIE_NAME].value)
            proxy_token = response.cookies[AUTH_COOKIE_NAME].value
            self.assertEqual(proxy_claims["sai"], original_start)
            self.assertNotEqual(proxy_claims["sid"], decode_auth_token(original_payload["token"])["sid"])

            stale_client = self.client_class()
            stale_client.cookies[AUTH_COOKIE_NAME] = original_payload["token"]
            stale_response = stale_client.get("/api/auth/session/validate")
            self.assertEqual(stale_response.status_code, 401)
            self.assertEqual(stale_response.json()["code"], "AUTH_SESSION_REVOKED")
            self.assertNotIn(AUTH_COOKIE_NAME, stale_response.cookies)

            response = self.client.post("/api/auth/proxy/stop", content_type="application/json")
            self.assertEqual(response.status_code, 200)
            actor_claims = decode_auth_token(response.cookies[AUTH_COOKIE_NAME].value)
            self.assertEqual(actor_claims["sai"], original_start)

            self.client.cookies[AUTH_COOKIE_NAME] = proxy_token
            response = self.client.get("/api/auth/session/validate")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["code"], "AUTH_SESSION_REVOKED")
            self.assertNotIn(AUTH_COOKIE_NAME, response.cookies)

    def test_proxy_target_uses_effective_whitelist_but_cannot_proxy_again(self):
        self.authenticate(self.admin)
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id, self.active.user_id}):
            response = self.client.post(
                "/api/auth/proxy/start",
                data=json.dumps({"userId": self.active.user_id}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["isSystemAdmin"])
            self.assertTrue(response.json()["isFullAccessUser"])
            self.assertTrue(response.json()["isProxying"])
            self.assertTrue(response.json()["canUseSystemAdmin"])
            self.assertTrue(response.json()["canManagePlatformSettings"])
            self.assertTrue(response.json()["canManageEmployeeAccountStatus"])
            self.assertFalse(response.json()["canStartProxy"])
            self.assertFalse(response.json()["canSwitchProxy"])
            self.assertFalse(response.json()["canProxy"])

            candidates_response = self.client.get("/api/auth/proxy/candidates")
            nested_response = self.client.post(
                "/api/auth/proxy/start",
                data=json.dumps({"userId": self.inactive.user_id}),
                content_type="application/json",
            )
            permissions_response = self.client.get("/api/org/permissions")

        self.assertEqual(candidates_response.status_code, 403)
        self.assertEqual(candidates_response.json()["code"], "PROXY_NESTING_FORBIDDEN")
        self.assertEqual(nested_response.status_code, 403)
        self.assertEqual(nested_response.json()["code"], "PROXY_NESTING_FORBIDDEN")
        self.assertEqual(permissions_response.status_code, 200)

    def test_proxy_target_does_not_inherit_actor_whitelist(self):
        self.authenticate(self.admin)
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.post(
                "/api/auth/proxy/start",
                data=json.dumps({"userId": self.active.user_id}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertFalse(payload["isSystemAdmin"])
            self.assertFalse(payload["canUseSystemAdmin"])
            self.assertFalse(payload["canManagePlatformSettings"])
            self.assertFalse(payload["canStartProxy"])
            self.assertFalse(payload["canSwitchProxy"])
            self.assertEqual(self.client.get("/api/org/permissions").status_code, 403)

    def test_proxy_target_uses_assigned_platform_settings_permission(self):
        OrganizationPermissionState.objects.update_or_create(
            state_id=1,
            defaults={
                "revision": 1,
                "rules": [{
                    "scopeType": "employee",
                    "targetId": self.active.user_id,
                    "targetName": self.active.name,
                    "sortOrder": 0,
                }],
                "manager_user_ids": [self.active.user_id],
            },
        )
        self.authenticate(self.admin)
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.post(
                "/api/auth/proxy/start",
                data=json.dumps({"userId": self.active.user_id}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertFalse(payload["isSystemAdmin"])
            self.assertFalse(payload["canUseSystemAdmin"])
            self.assertTrue(payload["canManagePlatformSettings"])
            self.assertTrue(payload["canConfigurePermissions"])
            self.assertFalse(payload["canStartProxy"])
            self.assertFalse(payload["canSwitchProxy"])
            self.assertEqual(self.client.get("/api/org/permissions").status_code, 200)

    def test_non_whitelist_account_cannot_start_proxy(self):
        self.authenticate(self.active)
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.post(
                "/api/auth/proxy/start",
                data=json.dumps({"userId": self.admin.user_id}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 403)

    def test_proxy_session_is_rejected_after_actor_is_removed_from_system_admins(self):
        self.authenticate(self.admin)
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.post(
                "/api/auth/proxy/start",
                data=json.dumps({"userId": self.active.user_id}),
                content_type="application/json",
            )
            proxy_token = response.cookies[AUTH_COOKIE_NAME].value

        self.client.cookies[AUTH_COOKIE_NAME] = proxy_token
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", set()):
            response = self.client.get("/api/auth/session/validate")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "PROXY_ACTOR_NOT_SYSTEM_ADMIN")

    def test_managed_departments_include_secondary_manager(self):
        department = Department.objects.create(
            dept_id=201,
            name="联合管理部门",
            manager_user_id=self.admin.user_id,
            manager_user_ids=[self.admin.user_id, self.active.user_id],
        )
        DepartmentManager.objects.create(department=department, employee=self.admin, is_primary=True, sort_order=0)
        DepartmentManager.objects.create(department=department, employee=self.active, sort_order=1)
        PlatformEnabledDepartment.objects.create(
            department=department,
            enabled_by=self.admin.user_id,
        )
        response = self.client.post(
            "/api/internal/org/users/managed-departments",
            data=json.dumps({"userIds": [self.active.user_id]}),
            content_type="application/json",
            HTTP_X_INTERNAL_SERVICE="crm-backend",
            HTTP_X_INTERNAL_AUTH_SECRET=INTERNAL_SECRET,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["orgRevision"], 0)
        self.assertEqual(response.json()["items"][0]["directDepartmentIds"], [department.dept_id])

    def test_introspection_returns_effective_system_admin_capability(self):
        token_payload = self.authenticate(self.admin)
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.post(
                "/api/internal/auth/introspect",
                data=json.dumps({"token": token_payload["token"]}),
                content_type="application/json",
                HTTP_X_INTERNAL_SERVICE="crm-backend",
                HTTP_X_INTERNAL_AUTH_SECRET=INTERNAL_SECRET,
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["isSystemAdmin"])
        self.assertTrue(response.json()["canUseSystemAdmin"])
        self.assertFalse(response.json()["isProxying"])
        self.assertNotIn("tokenPayload", response.json())

    def test_public_department_search_supports_pinyin_initials(self):
        Department.objects.create(dept_id=100, name="技术研发部")
        self.authenticate(self.active)
        response = self.client.get("/api/org/departments/search", {"keyword": "jsyfb"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["deptId"], 100)
        self.assertEqual(response.json()["items"][0]["pinyin"], "jishuyanfabu")

    def test_department_tree_survives_cross_department_cycle(self):
        Department.objects.create(dept_id=301, name="循环甲", parent_dept_id=302)
        Department.objects.create(dept_id=302, name="循环乙", parent_dept_id=301)
        self.authenticate(self.active)
        response = self.client.get("/api/org/departments/tree")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["deptId"], 301)

    @override_settings(ALLOWED_HOSTS=["testserver", "oa.hzmaijie.com"])
    @patch("identity_api.dingtalk.views.build_jsapi_config", return_value={"signature": "test"})
    def test_jsapi_signature_uses_explicit_origin_allowlist(self, _build_config):
        with patch.dict(
            "os.environ",
            {"DINGTALK_JSAPI_ALLOWED_ORIGINS": "https://oa.example.com"},
            clear=False,
        ):
            response = self.client.get(
                "/api/dingtalk/jsapi_config",
                {"url": "https://attacker.example.com/page"},
                HTTP_HOST="oa.hzmaijie.com",
            )
        self.assertEqual(response.status_code, 403)

    def test_cross_site_write_is_rejected_before_auth_action(self):
        self.authenticate(self.admin)
        response = self.client.post(
            "/api/auth/proxy/stop",
            content_type="application/json",
            HTTP_ORIGIN="https://subdomain.example.com",
            HTTP_SEC_FETCH_SITE="same-site",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "CROSS_ORIGIN_WRITE_BLOCKED")

    @override_settings(
        ALLOWED_HOSTS=["testserver", "oa.hzmaijie.com"],
        CSRF_TRUSTED_ORIGINS=["https://oa.hzmaijie.com"],
    )
    def test_public_https_origin_is_allowed_behind_http_gateway(self):
        self.authenticate(self.active)
        response = self.client.post(
            "/api/auth/logout",
            content_type="application/json",
            HTTP_HOST="oa.hzmaijie.com",
            HTTP_ORIGIN="https://oa.hzmaijie.com",
            HTTP_SEC_FETCH_SITE="same-origin",
        )
        self.assertEqual(response.status_code, 200)

    @patch("identity_api.auth.views.login_with_scan_code")
    def test_public_dingtalk_error_never_returns_raw_secret_detail(self, login_mock):
        login_mock.side_effect = DingTalkAPIError(
            "request failed: https://oapi.dingtalk.com/get?access_token=top-secret",
            detail={"appSecret": "app-secret", "nested": {"access_token": "token-secret"}},
        )
        response = self.client.post(
            "/api/auth/code",
            data=json.dumps({"authCode": "one-time-code"}),
            content_type="application/json",
        )
        payload = response.json()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(payload["code"], "DINGTALK_API_ERROR")
        self.assertNotIn("detail", payload)
        self.assertNotIn("top-secret", response.content.decode("utf-8"))
        self.assertNotIn("app-secret", response.content.decode("utf-8"))
        self.assertIn("[REDACTED]", payload["error"])

    def test_account_status_change_advances_organization_revision_once(self):
        OrganizationState.objects.filter(state_id=1).update(revision=7)
        original_updated_at = self.active.updated_at
        self.authenticate(self.admin)
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.post(
                f"/api/org/employees/{self.active.user_id}/account-status",
                data=json.dumps({"accountStatus": Employee.ACCOUNT_DISABLED}),
                content_type="application/json",
            )
            unchanged_response = self.client.post(
                f"/api/org/employees/{self.active.user_id}/account-status",
                data=json.dumps({"accountStatus": Employee.ACCOUNT_DISABLED}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["orgRevision"], 8)
        self.assertEqual(response["X-Organization-Revision"], "8")
        self.assertEqual(unchanged_response.json()["orgRevision"], 8)
        self.assertEqual(OrganizationState.objects.get(state_id=1).revision, 8)
        self.active.refresh_from_db()
        changed_updated_at = self.active.updated_at
        self.assertGreater(changed_updated_at, original_updated_at)

        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            self.client.post(
                f"/api/org/employees/{self.active.user_id}/account-status",
                data=json.dumps({"accountStatus": Employee.ACCOUNT_DISABLED}),
                content_type="application/json",
            )
        self.active.refresh_from_db()
        self.assertEqual(self.active.updated_at, changed_updated_at)

    @patch("identity_api.auth.views.login_with_scan_code")
    def test_login_avatar_change_advances_organization_revision(self, login_mock):
        OrganizationState.objects.filter(state_id=1).update(revision=3)
        login_mock.return_value = {
            "userId": self.active.user_id,
            "name": self.active.name,
            "avatarUrl": "https://example.com/new-avatar.png",
        }
        response = self.client.post(
            "/api/auth/code",
            data=json.dumps({"authCode": "valid-code"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.active.refresh_from_db()
        self.assertEqual(self.active.avatar_url, "https://example.com/new-avatar.png")
        self.assertEqual(OrganizationState.objects.get(state_id=1).revision, 4)

    @patch("identity_api.health.Redis.from_url")
    def test_auth_readiness_requires_worker_and_scheduler_heartbeats(self, redis_from_url):
        redis_from_url.return_value.ping.return_value = True
        with patch.dict("os.environ", {
            "DINGTALK_CLIENT_ID": "test-client-id",
            "DINGTALK_CLIENT_SECRET": "test-client-secret",
            "DINGTALK_CORP_ID": "test-corp-id",
        }, clear=False):
            cache.set(SYNC_WORKER_HEARTBEAT_KEY, "ready", timeout=30)
            cache.delete(SYNC_SCHEDULER_HEARTBEAT_KEY)
            response = self.client.get("/api/health/ready")
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json()["checks"]["syncScheduler"])

            cache.set(SYNC_SCHEDULER_HEARTBEAT_KEY, "ready", timeout=30)
            response = self.client.get("/api/health/ready")
            self.assertEqual(response.status_code, 200, response.json())
            self.assertTrue(response.json()["checks"]["syncWorker"])
            self.assertTrue(response.json()["checks"]["syncScheduler"])


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class OrganizationSnapshotConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        department = Department.objects.create(dept_id=901, name="快照测试部门")
        old_employee = Employee.objects.create(user_id="snapshot-old", name="旧快照员工")
        DepartmentEmployee.objects.create(department=department, employee=old_employee)
        PlatformEnabledDepartment.objects.create(department=department, enabled_by="snapshot-test")
        credential = InternalServiceCredential(service_name="snapshot-test", app_id="auth")
        credential.set_secret(INTERNAL_SECRET)
        credential.save()
        OrganizationState.objects.update_or_create(state_id=1, defaults={"revision": 0})

    def test_internal_org_response_keeps_data_and_revision_from_one_snapshot(self):
        if connection.vendor != "postgresql":
            self.skipTest("Repeatable-read snapshot behavior requires PostgreSQL")

        from identity_api.org import internal_views

        reader_started = threading.Event()
        writer_committed = threading.Event()
        result = {}
        original_parse_keyword = internal_views._parse_keyword

        def block_after_snapshot(payload):
            reader_started.set()
            if not writer_committed.wait(timeout=5):
                raise TimeoutError("Writer did not commit in time")
            return original_parse_keyword(payload)

        def run_reader():
            close_old_connections()
            try:
                client = self.client_class()
                result["response"] = client.post(
                    "/api/internal/org/users/search",
                    data=json.dumps({"keyword": "", "limit": 100}),
                    content_type="application/json",
                    HTTP_X_INTERNAL_SERVICE="snapshot-test",
                    HTTP_X_INTERNAL_AUTH_SECRET=INTERNAL_SECRET,
                )
            except Exception as exc:
                result["error"] = exc
            finally:
                connections.close_all()

        with patch("identity_api.org.internal_views._parse_keyword", side_effect=block_after_snapshot):
            reader = threading.Thread(target=run_reader, daemon=True)
            reader.start()
            self.assertTrue(reader_started.wait(timeout=5))

            with transaction.atomic():
                state = lock_organization_state()
                new_employee = Employee.objects.create(user_id="snapshot-new", name="新版本员工")
                DepartmentEmployee.objects.create(department_id=901, employee=new_employee)
                advance_organization_revision(state=state)
            writer_committed.set()
            reader.join(timeout=5)

        self.assertFalse(reader.is_alive())
        self.assertNotIn("error", result)
        response = result["response"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["orgRevision"], 0)
        self.assertEqual(
            {item["userId"] for item in response.json()["items"]},
            {"snapshot-old"},
        )
        self.assertEqual(OrganizationState.objects.get(state_id=1).revision, 1)
