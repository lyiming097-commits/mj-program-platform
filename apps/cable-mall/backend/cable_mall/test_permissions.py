from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.http import JsonResponse
from django.test import RequestFactory, TransactionTestCase

from identity_api.auth.middleware import AuthTokenMiddleware
from identity_api.auth.introspection import AuthIntrospectionError
from identity_api.security import SameOriginWriteMiddleware
from identity_api.models import Department, DepartmentEmployee, Employee

from . import views
from .models import (
    CableMallConfigurationRevision,
    CableMallOrganizationSyncState,
    CableMallPermissionRule,
)
from .permissions import get_user_cable_mall_scope, request_cable_mall_scope


class CableMallAuthorizationTests(TransactionTestCase):
    models = (
        Department,
        Employee,
        DepartmentEmployee,
        CableMallPermissionRule,
        CableMallConfigurationRevision,
        CableMallOrganizationSyncState,
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        existing_tables = set(connection.introspection.table_names())
        cls.created_models = []
        with connection.schema_editor() as schema_editor:
            for model in cls.models:
                if model._meta.db_table not in existing_tables:
                    schema_editor.create_model(model)
                    cls.created_models.append(model)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as schema_editor:
            for model in reversed(cls.created_models):
                schema_editor.delete_model(model)
        super().tearDownClass()

    def admin_request(self, method: str, path: str, payload: dict | None = None):
        factory = RequestFactory()
        if method == "get":
            request = factory.get(path)
        else:
            request = factory.post(
                path,
                data=json.dumps(payload or {}),
                content_type="application/json",
            )
        request.auth_user_id = "U-SYSTEM"
        request.auth_user_name = "平台管理员"
        request.auth_can_use_system_admin = True
        return request

    @staticmethod
    def payload(response) -> dict:
        return json.loads(response.content.decode("utf-8"))

    def test_auth_system_admin_capability_grants_cable_mall_admin_access(self):
        request = SimpleNamespace(
            auth_user_id="U-SYSTEM",
            auth_can_use_system_admin=True,
        )

        scope = request_cable_mall_scope(request)

        self.assertEqual(scope["permission"], CableMallPermissionRule.PERMISSION_ADMIN)
        self.assertTrue(scope["can_access_cable_mall"])
        self.assertTrue(scope["can_manage_cable_mall"])
        self.assertTrue(scope["is_system_admin"])

    def test_regular_user_still_requires_an_explicit_rule(self):
        request = SimpleNamespace(
            auth_user_id="U-REGULAR",
            auth_can_use_system_admin=False,
        )
        self.assertFalse(request_cable_mall_scope(request)["can_access_cable_mall"])

        CableMallPermissionRule.objects.create(
            permission=CableMallPermissionRule.PERMISSION_USER,
            scope_type=CableMallPermissionRule.SCOPE_EMPLOYEE,
            target_id="U-REGULAR",
            target_name="普通用户",
        )

        self.assertTrue(request_cable_mall_scope(request)["can_access_cable_mall"])
        self.assertFalse(request_cable_mall_scope(request)["can_manage_cable_mall"])

    def test_department_subtree_and_employee_exclusion_follow_crm_semantics(self):
        parent = Department.objects.create(dept_id=100, name="研发中心")
        child = Department.objects.create(dept_id=101, name="电子组", parent_dept_id=parent.dept_id)
        employee = Employee.objects.create(
            user_id="U-CHILD",
            name="子部门员工",
            status=Employee.STATUS_ACTIVE,
            account_status=Employee.ACCOUNT_ENABLED,
        )
        DepartmentEmployee.objects.create(department=child, employee=employee)
        CableMallPermissionRule.objects.create(
            permission=CableMallPermissionRule.PERMISSION_USER,
            scope_type=CableMallPermissionRule.SCOPE_DEPARTMENT,
            target_id=str(parent.dept_id),
            target_name=parent.name,
        )
        self.assertFalse(get_user_cable_mall_scope(employee.user_id)["can_access_cable_mall"])

        CableMallPermissionRule.objects.all().delete()
        CableMallPermissionRule.objects.create(
            permission=CableMallPermissionRule.PERMISSION_USER,
            scope_type=CableMallPermissionRule.SCOPE_DEPARTMENT_WITH_SUB,
            target_id=str(parent.dept_id),
            target_name=parent.name,
        )
        self.assertTrue(get_user_cable_mall_scope(employee.user_id)["can_access_cable_mall"])

        CableMallPermissionRule.objects.create(
            permission=CableMallPermissionRule.PERMISSION_USER,
            scope_type=CableMallPermissionRule.SCOPE_EXCLUDED_EMPLOYEE,
            target_id=employee.user_id,
            target_name=employee.name,
        )
        self.assertFalse(get_user_cable_mall_scope(employee.user_id)["can_access_cable_mall"])

    @patch("identity_api.auth.middleware.introspect_auth_token")
    def test_middleware_uses_only_auth_can_use_system_admin_capability(self, introspect):
        introspect.return_value = {
            "ok": True,
            "userId": "U-TARGET",
            "actorUserId": "U-ADMIN",
            "name": "被代理用户",
            "actorName": "平台管理员",
            "isProxying": True,
            "canUseSystemAdmin": False,
            "claims": {},
        }
        captured = {}

        def get_response(request):
            captured["request"] = request
            return JsonResponse({"ok": True})

        request = RequestFactory().get(
            "/api/cable-mall/permissions/current",
            HTTP_AUTHORIZATION="Bearer test-token",
        )

        response = AuthTokenMiddleware(get_response)(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(captured["request"].auth_is_proxy)
        self.assertFalse(captured["request"].auth_can_use_system_admin)
        self.assertFalse(request_cable_mall_scope(captured["request"])["can_access_cable_mall"])

    @patch(
        "identity_api.auth.middleware.introspect_auth_token",
        side_effect=AuthIntrospectionError("expired", 401),
    )
    def test_rejected_stale_request_does_not_delete_auth_cookie(self, _introspect):
        request = RequestFactory().get(
            "/api/cable-mall/permissions/current",
            HTTP_AUTHORIZATION="Bearer stale-token",
        )

        response = AuthTokenMiddleware(lambda _request: JsonResponse({"ok": True}))(request)

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("mj_auth_token", response.cookies)

    @patch("identity_api.auth.middleware.introspect_auth_token")
    def test_middleware_rejects_non_object_claims_without_raising(self, introspect):
        introspect.return_value = {
            "ok": True,
            "userId": "U-TARGET",
            "claims": [],
            "requestId": "auth-request-1",
        }
        request = RequestFactory().get(
            "/api/cable-mall/permissions/current",
            HTTP_AUTHORIZATION="Bearer test-token",
            HTTP_X_REQUEST_ID="incoming-request-1",
        )

        response = AuthTokenMiddleware(lambda _request: JsonResponse({"ok": True}))(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(payload["code"], "INVALID_AUTH_RESPONSE")
        self.assertEqual(payload["requestId"], "auth-request-1")
        introspect.assert_called_once_with("test-token", request_id="incoming-request-1")

    @patch("identity_api.auth.middleware.introspect_auth_token")
    def test_middleware_preserves_introspection_error_contract(self, introspect):
        introspect.side_effect = AuthIntrospectionError(
            "auth unavailable",
            503,
            code="AUTH_SERVICE_UNAVAILABLE",
            request_id="auth-request-2",
        )
        request = RequestFactory().get(
            "/api/cable-mall/permissions/current",
            HTTP_AUTHORIZATION="Bearer test-token",
            HTTP_X_REQUEST_ID="incoming-request-2",
        )

        response = AuthTokenMiddleware(lambda _request: JsonResponse({"ok": True}))(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["code"], "AUTH_SERVICE_UNAVAILABLE")
        self.assertEqual(payload["requestId"], "auth-request-2")
        introspect.assert_called_once_with("test-token", request_id="incoming-request-2")

    def test_same_site_and_cross_site_writes_are_rejected(self):
        middleware = SameOriginWriteMiddleware(lambda _request: JsonResponse({"ok": True}))
        for fetch_site in ("same-site", "cross-site"):
            request = RequestFactory().post(
                "/api/cable-mall/permissions",
                data="{}",
                content_type="application/json",
                HTTP_HOST="portal.example.test",
                HTTP_ORIGIN="https://subdomain.example.test",
                HTTP_SEC_FETCH_SITE=fetch_site,
            )
            response = middleware(request)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(json.loads(response.content)["code"], "CROSS_ORIGIN_WRITE_BLOCKED")

    def test_same_origin_write_with_explicit_port_is_allowed(self):
        middleware = SameOriginWriteMiddleware(lambda _request: JsonResponse({"ok": True}))
        request = RequestFactory().post(
            "/api/cable-mall/permissions",
            data="{}",
            content_type="application/json",
            HTTP_HOST="localhost:18080",
            HTTP_ORIGIN="http://localhost:18080",
            HTTP_SEC_FETCH_SITE="same-origin",
        )

        self.assertEqual(middleware(request).status_code, 200)

    @patch("cable_mall.permissions.get_auth_organization_snapshot")
    def test_permission_directory_uses_and_materializes_auth_snapshot(self, get_snapshot):
        get_snapshot.return_value = (
            [{"deptId": 100, "name": "销售部", "parentDeptId": None}],
            [{
                "userId": "U-100",
                "rawName": "销售人员",
                "name": "销售人员",
                "status": Employee.STATUS_ACTIVE,
                "accountStatus": Employee.ACCOUNT_ENABLED,
                "departments": [{"deptId": 100, "name": "销售部"}],
            }],
            12,
        )

        response = views.cable_mall_permission_directory(
            self.admin_request("get", "/api/cable-mall/permissions/directory")
        )

        self.assertEqual(response.status_code, 200, self.payload(response))
        data = self.payload(response)
        self.assertEqual(data["directorySource"], "auth")
        self.assertEqual(data["orgRevision"], 12)
        self.assertEqual(data["departments"][0]["deptId"], 100)
        self.assertEqual(data["employees"][0]["userId"], "U-100")
        self.assertTrue(DepartmentEmployee.objects.filter(department_id=100, employee_id="U-100").exists())
        self.assertEqual(CableMallOrganizationSyncState.objects.get().org_revision, 12)

    @patch("cable_mall.views.refresh_auth_organization_snapshot")
    def test_permission_save_requires_and_advances_configuration_revision(self, refresh_snapshot):
        refresh_snapshot.return_value = {"refreshed": False, "orgRevision": 12}
        Employee.objects.create(
            user_id="U-100",
            name="销售人员",
            status=Employee.STATUS_ACTIVE,
            account_status=Employee.ACCOUNT_ENABLED,
        )
        get_response = views.cable_mall_permissions_collection(
            self.admin_request("get", "/api/cable-mall/permissions")
        )
        revision = self.payload(get_response)["revision"]

        response = views.cable_mall_permissions_collection(
            self.admin_request("post", "/api/cable-mall/permissions", {
                "revision": revision,
                "orgRevision": "12",
                "items": [{
                    "permission": "user",
                    "scopeType": "employee",
                    "targetId": "U-100",
                    "targetName": "客户端旧名称",
                }],
            })
        )

        self.assertEqual(response.status_code, 200, self.payload(response))
        data = self.payload(response)
        self.assertEqual(data["revision"], str(int(revision) + 1))
        self.assertEqual(data["orgRevision"], 12)
        self.assertEqual(data["items"][0]["targetName"], "销售人员")

    @patch("cable_mall.views.refresh_auth_organization_snapshot")
    def test_permission_save_accepts_subtree_and_excluded_employee_scopes(self, refresh_snapshot):
        refresh_snapshot.return_value = {"refreshed": False, "orgRevision": 12}
        Department.objects.create(dept_id=100, name="研发中心")
        Employee.objects.create(
            user_id="U-100",
            name="研发人员",
            status=Employee.STATUS_ACTIVE,
            account_status=Employee.ACCOUNT_ENABLED,
        )
        revision = views._configuration_revision_value(views.CABLE_MALL_CONFIGURATION_PERMISSIONS)

        response = views.cable_mall_permissions_collection(
            self.admin_request("post", "/api/cable-mall/permissions", {
                "revision": revision,
                "orgRevision": "12",
                "items": [
                    {
                        "permission": "user",
                        "scopeType": "departmentSub",
                        "targetId": "100",
                        "targetName": "旧部门名",
                    },
                    {
                        "permission": "user",
                        "scopeType": "excludedEmployee",
                        "targetId": "U-100",
                        "targetName": "旧人员名",
                    },
                ],
            })
        )

        self.assertEqual(response.status_code, 200, self.payload(response))
        items_by_scope = {item["scopeType"]: item for item in self.payload(response)["items"]}
        self.assertEqual(items_by_scope["departmentSub"]["targetName"], "研发中心")
        self.assertEqual(items_by_scope["excludedEmployee"]["targetName"], "研发人员")

    @patch("cable_mall.views.refresh_auth_organization_snapshot")
    def test_permission_save_rejects_stale_configuration_revision(self, refresh_snapshot):
        refresh_snapshot.return_value = {"refreshed": False, "orgRevision": 12}
        CableMallConfigurationRevision.objects.create(key="permissions", revision=2)

        response = views.cable_mall_permissions_collection(
            self.admin_request("post", "/api/cable-mall/permissions", {
                "revision": "1",
                "orgRevision": "12",
                "items": [],
            })
        )

        self.assertEqual(response.status_code, 409, self.payload(response))
        self.assertEqual(self.payload(response)["code"], "REVISION_CONFLICT")
        self.assertEqual(self.payload(response)["revision"], "2")

    @patch("cable_mall.views.refresh_auth_organization_snapshot")
    def test_permission_save_rejects_stale_organization_revision(self, refresh_snapshot):
        refresh_snapshot.return_value = {"refreshed": True, "orgRevision": 13}

        response = views.cable_mall_permissions_collection(
            self.admin_request("post", "/api/cable-mall/permissions", {
                "revision": "1",
                "orgRevision": "12",
                "items": [],
            })
        )

        self.assertEqual(response.status_code, 409, self.payload(response))
        self.assertEqual(self.payload(response)["code"], "ORG_REVISION_CONFLICT")
        self.assertEqual(self.payload(response)["orgRevision"], "13")
