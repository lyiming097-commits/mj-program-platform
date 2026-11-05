from __future__ import annotations

import json
from threading import Event, Thread
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.http import JsonResponse
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings

from . import org_client, permissions, views
from .models import (
    AppConfigurationRevision,
    AppPermissionRule,
)
from .org_client import AuthOrgClientError, AuthOrgRevisionChanged
from .platform import SameOriginWriteMiddleware


class AppPlatformTests(TestCase):
    def test_health_endpoints_are_public(self):
        for path in (
            "/api/health/",
            "/api/health/live",
            "/api/health/ready",
            "/api/approval-center/health/",
            "/api/approval-center/health/live",
            "/api/approval-center/health/ready",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["ok"])

    def test_readiness_reports_database_failure(self):
        for path in ("/api/health/ready", "/api/approval-center/health/ready"):
            with self.subTest(path=path):
                with patch(
                    "approval_center_api.views.connection.cursor",
                    side_effect=RuntimeError("database unavailable"),
                ):
                    response = self.client.get(path)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["code"], "DATABASE_UNAVAILABLE")

    def test_app_health_public_paths_are_exact(self):
        response = self.client.get("/api/approval-center/health/ready/extra")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "MISSING_AUTH_TOKEN")

    def test_workspace_requires_login(self):
        response = self.client.get("/api/approval-center/workspace")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "MISSING_AUTH_TOKEN")

    def test_cross_origin_write_is_blocked(self):
        middleware = SameOriginWriteMiddleware(lambda _request: JsonResponse({"ok": True}))
        request = RequestFactory().post(
            "/api/approval-center/session/",
            HTTP_HOST="platform.example.test",
            HTTP_ORIGIN="https://other.example.test",
            HTTP_SEC_FETCH_SITE="cross-site",
        )
        response = middleware(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["code"], "CROSS_ORIGIN_WRITE_BLOCKED")

    @override_settings(CSRF_TRUSTED_ORIGINS=["https://oa.hzmaijie.com:4433"])
    def test_configured_public_origin_write_is_allowed_behind_http_gateway(self):
        middleware = SameOriginWriteMiddleware(lambda _request: JsonResponse({"ok": True}))
        request = RequestFactory().post(
            "/api/approval-center/applications",
            HTTP_HOST="oa.hzmaijie.com:4433",
            HTTP_ORIGIN="https://oa.hzmaijie.com:4433",
            HTTP_SEC_FETCH_SITE="same-origin",
        )

        response = middleware(request)

        self.assertEqual(response.status_code, 200)


class AppPermissionTests(TestCase):
    departments = [
        {"deptId": 1, "name": "总部", "parentDeptId": None},
        {"deptId": 2, "name": "研发部", "parentDeptId": 1},
    ]
    employees = [
        {
            "userId": "user-1",
            "name": "管理员甲",
            "rawName": "管理员甲",
            "status": "在职",
            "accountStatus": "启用",
            "departments": [{"deptId": 2, "name": "研发部"}],
        },
        {
            "userId": "user-2",
            "name": "成员乙",
            "rawName": "成员乙",
            "status": "在职",
            "accountStatus": "启用",
            "departments": [{"deptId": 2, "name": "研发部"}],
        },
    ]

    def setUp(self):
        self.factory = RequestFactory()

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        user_id: str = "system-admin",
        system_admin: bool = True,
        proxy: bool = False,
    ):
        if method.lower() == "get":
            request = self.factory.get(path)
        else:
            request = self.factory.post(
                path,
                data=json.dumps(payload or {}, ensure_ascii=False),
                content_type="application/json",
            )
        request.auth_user_id = user_id
        request.auth_user_name = user_id
        request.auth_actor_user_id = "actor-admin" if proxy else user_id
        request.auth_actor_name = "实际操作人" if proxy else user_id
        request.auth_is_proxy = proxy
        request.auth_can_use_system_admin = system_admin
        return request

    @staticmethod
    def payload(response) -> dict:
        return json.loads(response.content.decode("utf-8"))

    def create_rule(
        self,
        *,
        scope_type: str = AppPermissionRule.SCOPE_EMPLOYEE,
        target_id: str = "user-1",
        target_name: str = "管理员甲",
    ) -> AppPermissionRule:
        return AppPermissionRule.objects.create(
            permission=AppPermissionRule.PERMISSION_ADMIN,
            scope_type=scope_type,
            target_id=target_id,
            target_name=target_name,
        )

    def test_session_exposes_system_and_assigned_admin_permissions(self):
        response = views.session(self.request("get", "/api/approval-center/session/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payload(response)["appPermission"], "admin")
        self.assertTrue(self.payload(response)["canManageApp"])

        self.create_rule()
        response = views.session(self.request(
            "get",
            "/api/approval-center/session/",
            user_id="user-1",
            system_admin=False,
        ))
        self.assertEqual(self.payload(response)["appPermission"], "admin")
        self.assertTrue(self.payload(response)["canManageApp"])

    def test_proxy_does_not_inherit_system_admin_but_can_use_assigned_permission(self):
        request = self.request(
            "get",
            "/api/approval-center/session/",
            user_id="user-1",
            system_admin=False,
            proxy=True,
        )
        response = views.session(request)
        self.assertEqual(self.payload(response)["appPermission"], "")
        self.assertFalse(self.payload(response)["canManageApp"])

        self.create_rule()
        response = views.session(request)
        self.assertEqual(self.payload(response)["appPermission"], "admin")
        self.assertTrue(self.payload(response)["canManageApp"])

    def test_department_rules_are_enforced(self):
        self.create_rule(
            scope_type=AppPermissionRule.SCOPE_DEPARTMENT_WITH_SUB,
            target_id="1",
            target_name="总部",
        )
        with patch.object(
            permissions,
            "get_auth_user_department_scope",
            return_value={
                "directDepartmentIds": {"2"},
                "ancestorDepartmentIds": {"1", "2"},
                "orgRevision": 7,
            },
        ):
            self.assertEqual(permissions.get_user_app_permission("user-2"), "admin")

    def test_regular_user_cannot_read_or_write_permission_configuration(self):
        requests = [
            (views.permissions_collection, self.request(
                "get",
                "/api/approval-center/permissions",
                user_id="regular",
                system_admin=False,
            )),
            (views.permissions_collection, self.request(
                "post",
                "/api/approval-center/permissions",
                {"items": [], "revision": "1", "orgRevision": "1"},
                user_id="regular",
                system_admin=False,
            )),
            (views.permission_directory, self.request(
                "get",
                "/api/approval-center/permissions/directory",
                user_id="regular",
                system_admin=False,
            )),
        ]
        for view, request in requests:
            with self.subTest(path=request.path, method=request.method):
                response = view(request)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.payload(response)["code"], "APP_ADMIN_REQUIRED")

    def test_system_admin_can_bootstrap_and_assigned_admin_can_read_rules(self):
        response = views.permissions_collection(self.request(
            "get",
            "/api/approval-center/permissions",
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payload(response), {"items": [], "revision": "1"})

        self.create_rule()
        response = views.permissions_collection(self.request(
            "get",
            "/api/approval-center/permissions",
            user_id="user-1",
            system_admin=False,
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payload(response)["items"][0]["permission"], "admin")

    def test_directory_uses_auth_snapshot_contract(self):
        with patch.object(
            views,
            "get_auth_organization_snapshot",
            return_value=(self.departments, self.employees, 11),
        ):
            response = views.permission_directory(self.request(
                "get",
                "/api/approval-center/permissions/directory",
            ))

        self.assertEqual(response.status_code, 200)
        data = self.payload(response)
        self.assertEqual(data["directorySource"], "auth")
        self.assertEqual(data["orgRevision"], 11)
        self.assertEqual(data["roles"], [])
        self.assertEqual(data["departments"][0]["deptId"], 1)
        self.assertEqual(data["departments"][0]["children"][0]["deptId"], 2)
        self.assertEqual([item["userId"] for item in data["employees"]], ["user-1", "user-2"])

    def test_employee_directory_is_admin_only_and_uses_auth_snapshot_contract(self):
        denied = views.employee_directory(self.request(
            "get",
            "/api/approval-center/directory/employees",
            user_id="regular",
            system_admin=False,
        ))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.payload(denied)["code"], "APP_ADMIN_REQUIRED")

        with patch.object(
            views,
            "get_auth_organization_snapshot",
            return_value=(self.departments, self.employees, 11),
        ):
            response = views.employee_directory(self.request(
                "get",
                "/api/approval-center/directory/employees",
            ))

        self.assertEqual(response.status_code, 200)
        data = self.payload(response)
        self.assertEqual(data["directorySource"], "auth")
        self.assertEqual(data["orgRevision"], 11)
        self.assertEqual(data["count"], 2)
        self.assertEqual([item["userId"] for item in data["items"]], ["user-1", "user-2"])

    def test_post_atomically_replaces_rules_and_advances_revision(self):
        AppConfigurationRevision.objects.create(key="permissions", revision=1)
        request = self.request(
            "post",
            "/api/approval-center/permissions",
            {
                "revision": "1",
                "orgRevision": "11",
                "items": [{
                    "permission": "admin",
                    "scopeType": "employee",
                    "targetId": "user-1",
                    "targetName": "伪造名称",
                    "sortOrder": 3,
                }],
            },
        )
        with patch.object(
            views,
            "get_auth_organization_snapshot",
            return_value=(self.departments, self.employees, 11),
        ):
            response = views.permissions_collection(request)

        self.assertEqual(response.status_code, 200, self.payload(response))
        data = self.payload(response)
        self.assertTrue(data["ok"])
        self.assertEqual(data["revision"], "2")
        self.assertEqual(data["orgRevision"], 11)
        self.assertEqual(data["items"][0]["targetName"], "管理员甲")
        rule = AppPermissionRule.objects.get()
        self.assertEqual(rule.created_by, "system-admin")
        self.assertEqual(rule.sort_order, 3)
        self.assertEqual(AppConfigurationRevision.objects.get(key="permissions").revision, 2)

    def test_proxy_permission_save_audits_real_actor(self):
        AppConfigurationRevision.objects.create(key="permissions", revision=1)
        self.create_rule(target_id="user-1", target_name="管理员甲")
        request = self.request(
            "post",
            "/api/approval-center/permissions",
            {
                "revision": "1",
                "orgRevision": "11",
                "items": [{
                    "permission": "admin",
                    "scopeType": "employee",
                    "targetId": "user-2",
                    "targetName": "成员乙",
                }],
            },
            user_id="user-1",
            system_admin=False,
            proxy=True,
        )
        with patch.object(
            views,
            "get_auth_organization_snapshot",
            return_value=(self.departments, self.employees, 11),
        ):
            response = views.permissions_collection(request)

        self.assertEqual(response.status_code, 200, self.payload(response))
        rule = AppPermissionRule.objects.get()
        self.assertEqual(rule.target_id, "user-2")
        self.assertEqual(rule.created_by, "actor-admin")

    def test_post_rejects_missing_and_conflicting_revisions_without_changes(self):
        AppConfigurationRevision.objects.create(key="permissions", revision=3)
        original = self.create_rule()
        cases = [
            ({"revision": "3", "items": []}, 400, "ORG_REVISION_REQUIRED"),
            ({"revision": "3", "orgRevision": "10", "items": []}, 409, "ORG_REVISION_CONFLICT"),
            ({"orgRevision": "11", "items": []}, 400, "REVISION_REQUIRED"),
            ({"revision": "2", "orgRevision": "11", "items": []}, 409, "REVISION_CONFLICT"),
        ]
        for payload, status, code in cases:
            with self.subTest(code=code), patch.object(
                views,
                "get_auth_organization_snapshot",
                return_value=(self.departments, self.employees, 11),
            ):
                response = views.permissions_collection(self.request(
                    "post",
                    "/api/approval-center/permissions",
                    payload,
                ))
            self.assertEqual(response.status_code, status)
            self.assertEqual(self.payload(response)["code"], code)
            self.assertEqual(list(AppPermissionRule.objects.values_list("id", flat=True)), [original.id])
            self.assertEqual(AppConfigurationRevision.objects.get(key="permissions").revision, 3)

    def test_invalid_rules_do_not_partially_replace_existing_configuration(self):
        AppConfigurationRevision.objects.create(key="permissions", revision=1)
        original = self.create_rule()
        inactive_employee = {
            "userId": "inactive-user",
            "name": "离职人员",
            "status": "离职",
            "accountStatus": "停用",
        }
        cases = [
            [{"permission": "user", "scopeType": "employee", "targetId": "user-2"}],
            [{"permission": "admin", "scopeType": "role", "targetId": "1"}],
            [{"permission": "admin", "scopeType": "excludedEmployee", "targetId": "user-2"}],
            [{"permission": "admin", "scopeType": "employee", "targetId": "x" * 65}],
            [{"permission": "admin", "scopeType": "employee", "targetId": "user-2", "targetName": "x" * 256}],
            [{"permission": "admin", "scopeType": "department", "targetId": "not-a-number"}],
            [{"permission": "admin", "scopeType": "employee", "targetId": "missing-user"}],
            [{"permission": "admin", "scopeType": "employee", "targetId": "inactive-user"}],
            [
                {"permission": "admin", "scopeType": "employee", "targetId": "user-2"},
                {"permission": "admin", "scopeType": "employee", "targetId": "user-2"},
            ],
            [{"permission": "admin", "scopeType": "employee", "targetId": "user-2", "sortOrder": -1}],
        ]
        for items in cases:
            with self.subTest(items=items), patch.object(
                views,
                "get_auth_organization_snapshot",
                return_value=(self.departments, [*self.employees, inactive_employee], 11),
            ):
                response = views.permissions_collection(self.request(
                    "post",
                    "/api/approval-center/permissions",
                    {"revision": "1", "orgRevision": "11", "items": items},
                ))
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.payload(response)["code"], "INVALID_PERMISSION_RULE")
            self.assertEqual(list(AppPermissionRule.objects.values_list("id", flat=True)), [original.id])
            self.assertEqual(AppConfigurationRevision.objects.get(key="permissions").revision, 1)

    def test_category_permission_rejects_retired_excluded_scope(self):
        with self.assertRaisesMessage(ValueError, "范围类型无效"):
            permissions.replace_category_permission_rules(
                1,
                [{
                    "permission": "admin",
                    "scopeType": "excludedEmployee",
                    "targetId": "user-2",
                }],
                departments=self.departments,
                employees=self.employees,
            )

    def test_auth_org_failure_is_reported_for_admin_endpoints_and_fails_closed_in_session(self):
        with patch.object(
            views,
            "get_auth_organization_snapshot",
            side_effect=AuthOrgClientError("组织服务不可用", 503),
        ):
            response = views.permission_directory(self.request(
                "get",
                "/api/approval-center/permissions/directory",
            ))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.payload(response)["code"], "AUTH_ORG_UNAVAILABLE")

        self.create_rule(
            scope_type=AppPermissionRule.SCOPE_DEPARTMENT,
            target_id="2",
            target_name="研发部",
        )
        with patch.object(
            permissions,
            "get_auth_user_department_scope",
            side_effect=AuthOrgClientError("组织服务不可用", 503),
        ):
            response = views.session(self.request(
                "get",
                "/api/approval-center/session/",
                user_id="user-2",
                system_admin=False,
            ))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.payload(response)["canManageApp"])
        self.assertEqual(self.payload(response)["appPermission"], "")


@skipUnless(connection.vendor == "postgresql", "row-lock regression requires PostgreSQL")
class AppPermissionConcurrencyTests(TransactionTestCase):
    def request(self, method: str, payload: dict | None = None):
        factory = RequestFactory()
        if method == "get":
            request = factory.get("/api/approval-center/permissions")
        else:
            request = factory.post(
                "/api/approval-center/permissions",
                data=json.dumps(payload or {}, ensure_ascii=False),
                content_type="application/json",
            )
        request.auth_user_id = "system-admin"
        request.auth_user_name = "system-admin"
        request.auth_actor_user_id = "system-admin"
        request.auth_actor_name = "system-admin"
        request.auth_is_proxy = False
        request.auth_can_use_system_admin = True
        return request

    def test_get_rules_and_revision_are_one_locked_snapshot(self):
        AppConfigurationRevision.objects.create(key="permissions", revision=1)
        AppPermissionRule.objects.create(
            permission="admin",
            scope_type="employee",
            target_id="old-admin",
            target_name="旧管理员",
        )
        departments = [{"deptId": 1, "name": "总部", "parentDeptId": None}]
        employees = [
            {
                "userId": "old-admin",
                "name": "旧管理员",
                "status": "在职",
                "accountStatus": "启用",
            },
            {
                "userId": "new-admin",
                "name": "新管理员",
                "status": "在职",
                "accountStatus": "启用",
            },
        ]
        post_payload = {
            "revision": "1",
            "orgRevision": "8",
            "items": [{
                "permission": "admin",
                "scopeType": "employee",
                "targetId": "new-admin",
                "targetName": "新管理员",
                "sortOrder": 0,
            }],
        }

        read_started = Event()
        release_read = Event()
        post_lock_attempted = Event()
        post_done = Event()
        responses = {}
        errors = []
        original_list = views.list_app_permission_rules
        original_lock = views._lock_configuration_revision

        def delayed_list():
            items = original_list()
            read_started.set()
            if not release_read.wait(5):
                raise TimeoutError("permission snapshot read was not released")
            return items

        def observed_lock(payload):
            post_lock_attempted.set()
            return original_lock(payload)

        def run_get():
            close_old_connections()
            try:
                responses["get"] = views.permissions_collection(self.request("get"))
            except BaseException as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        def run_post():
            close_old_connections()
            try:
                responses["post"] = views.permissions_collection(self.request("post", post_payload))
            except BaseException as exc:
                errors.append(exc)
            finally:
                post_done.set()
                close_old_connections()

        get_thread = Thread(target=run_get)
        post_thread = Thread(target=run_post)
        post_started = False
        with (
            patch.object(views, "list_app_permission_rules", side_effect=delayed_list),
            patch.object(views, "_lock_configuration_revision", side_effect=observed_lock),
            patch.object(
                views,
                "get_auth_organization_snapshot",
                return_value=(departments, employees, 8),
            ),
        ):
            get_thread.start()
            read_reached = read_started.wait(5)
            if read_reached:
                post_thread.start()
                post_started = True
            lock_reached = post_lock_attempted.wait(5) if post_started else False
            post_completed_before_release = post_done.wait(1) if lock_reached else False
            release_read.set()
            get_thread.join(5)
            if post_started:
                post_thread.join(5)

        self.assertTrue(read_reached)
        self.assertTrue(lock_reached)
        self.assertFalse(post_completed_before_release)
        self.assertFalse(get_thread.is_alive())
        self.assertFalse(post_thread.is_alive())
        self.assertEqual(errors, [])

        get_data = json.loads(responses["get"].content)
        post_data = json.loads(responses["post"].content)
        self.assertEqual(get_data["revision"], "1")
        self.assertEqual([item["targetId"] for item in get_data["items"]], ["old-admin"])
        self.assertEqual(responses["post"].status_code, 200)
        self.assertEqual(post_data["revision"], "2")
        self.assertEqual(
            list(AppPermissionRule.objects.values_list("target_id", flat=True)),
            ["new-admin"],
        )


class AppOrgClientTests(TestCase):
    def test_user_department_scope_includes_department_ancestors(self):
        with patch.object(org_client, "_post", return_value={
            "ok": True,
            "orgRevision": 9,
            "items": [{
                "userId": "user-1",
                "found": True,
                "matchesFilters": True,
                "departmentIds": [2],
                "departments": [{
                    "deptId": 2,
                    "departmentPath": [{"deptId": 1}, {"deptId": 2}],
                }],
            }],
        }) as post:
            scope = org_client.get_auth_user_department_scope("user-1")

        self.assertEqual(scope["directDepartmentIds"], {"2"})
        self.assertEqual(scope["ancestorDepartmentIds"], {"1", "2"})
        self.assertEqual(scope["orgRevision"], 9)
        post.assert_called_once_with("users/departments", {
            "userIds": ["user-1"],
            "status": "active",
            "accountStatus": "enabled",
            "includeDepartmentPath": True,
            "includeEmployeeProfiles": False,
        })

    def test_snapshot_retries_when_auth_revision_changes(self):
        departments = [{"deptId": 1, "name": "总部"}]
        employees = [{"userId": "user-1", "status": "在职", "accountStatus": "启用"}]
        with patch.object(org_client, "_search_all", side_effect=[
            (departments, 7),
            AuthOrgRevisionChanged("changed", 409),
            (departments, 8),
            (employees, 8),
        ]) as search_all:
            result = org_client.get_auth_organization_snapshot()

        self.assertEqual(result, (departments, employees, 8))
        self.assertEqual(search_all.call_count, 4)
