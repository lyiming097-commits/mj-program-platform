import json

from django.test import TestCase
from unittest.mock import patch

from identity_api.auth.session import create_auth_session_token
from identity_api.auth.tokens import AUTH_COOKIE_NAME
from identity_api.models import (
    Department,
    DepartmentEmployee,
    Employee,
    InternalServiceCredential,
    OrganizationPermissionState,
    OrganizationState,
    PlatformDepartmentState,
    PlatformEnabledDepartment,
)
from identity_api.org.organization_access import get_platform_enabled_department_ids


INTERNAL_SECRET = "organization-access-test-secret-0123456789"


class OrganizationAccessTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_SEC_FETCH_SITE"] = "same-origin"
        self.root = Department.objects.create(dept_id=1, name="迈杰", parent_dept_id=None)
        self.enabled_team = Department.objects.create(
            dept_id=2,
            name="研发部",
            parent_dept_id=self.root.dept_id,
        )
        self.disabled_team = Department.objects.create(
            dept_id=3,
            name="临时事务组",
            parent_dept_id=self.root.dept_id,
        )
        self.admin = Employee.objects.create(user_id="admin", name="平台管理员")
        self.root_member = Employee.objects.create(user_id="root-member", name="总部员工")
        self.enabled_member = Employee.objects.create(user_id="enabled-member", name="研发员工")
        self.disabled_member = Employee.objects.create(user_id="disabled-member", name="事务员工")
        DepartmentEmployee.objects.bulk_create([
            DepartmentEmployee(department=self.root, employee=self.root_member),
            DepartmentEmployee(department=self.enabled_team, employee=self.enabled_member),
            DepartmentEmployee(department=self.disabled_team, employee=self.disabled_member),
        ])
        OrganizationState.objects.update_or_create(state_id=1, defaults={"revision": 5})
        PlatformDepartmentState.objects.update_or_create(
            state_id=1,
            defaults={"configured": True, "revision": 1},
        )
        PlatformEnabledDepartment.objects.all().delete()
        credential = InternalServiceCredential(service_name="task-management-backend", app_id="task-management")
        credential.set_secret(INTERNAL_SECRET)
        credential.save()

    def authenticate(self, employee):
        self.client.cookies[AUTH_COOKIE_NAME] = create_auth_session_token(employee)["token"]

    def internal_post(self, path, payload):
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_INTERNAL_SERVICE="task-management-backend",
            HTTP_X_INTERNAL_AUTH_SECRET=INTERNAL_SECRET,
        )

    def test_unconfigured_state_temporarily_falls_back_to_all_existing_departments(self):
        PlatformDepartmentState.objects.filter(state_id=1).delete()

        self.assertEqual(
            get_platform_enabled_department_ids(),
            {self.root.dept_id, self.enabled_team.dept_id, self.disabled_team.dept_id},
        )

    def test_enabling_child_keeps_parent_disabled_and_advances_org_revision(self):
        self.authenticate(self.admin)
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.put(
                "/api/org/enabled-departments",
                data=json.dumps({
                    "departmentIds": [self.enabled_team.dept_id],
                    "revision": 1,
                    "orgRevision": 5,
                }),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["departmentIds"], [2])
        self.assertEqual(response.json()["revision"], 2)
        self.assertEqual(response.json()["orgRevision"], 6)
        self.assertEqual(
            set(PlatformEnabledDepartment.objects.values_list("department_id", flat=True)),
            {2},
        )

        departments_response = self.internal_post(
            "/api/internal/org/departments/search",
            {"keyword": "", "includeDepartmentPath": True, "limit": 100, "offset": 0},
        )
        users_response = self.internal_post(
            "/api/internal/org/users/search",
            {
                "keyword": "",
                "status": "active",
                "accountStatus": "enabled",
                "includeDepartments": True,
                "includeDepartmentPath": True,
                "limit": 100,
                "offset": 0,
            },
        )

        self.assertEqual(departments_response.status_code, 200, departments_response.content)
        self.assertEqual([item["deptId"] for item in departments_response.json()["items"]], [2])
        self.assertIsNone(departments_response.json()["items"][0]["parentDeptId"])
        self.assertEqual(
            [item["deptId"] for item in departments_response.json()["items"][0]["departmentPath"]],
            [2],
        )
        self.assertEqual(users_response.status_code, 200, users_response.content)
        self.assertEqual([item["userId"] for item in users_response.json()["items"]], ["enabled-member"])
        self.assertIsNone(users_response.json()["items"][0]["departments"][0]["parentDeptId"])

    def test_enabled_department_update_rejects_stale_organization_revision(self):
        self.authenticate(self.admin)
        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.put(
                "/api/org/enabled-departments",
                data=json.dumps({
                    "departmentIds": [self.root.dept_id],
                    "revision": 1,
                    "orgRevision": 4,
                }),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "ORG_REVISION_CONFLICT")
        self.assertFalse(PlatformEnabledDepartment.objects.exists())

    def test_authenticated_employee_can_read_enabled_departments_without_manage_permission(self):
        PlatformEnabledDepartment.objects.create(department=self.enabled_team, enabled_by=self.admin.user_id)
        self.authenticate(self.root_member)

        response = self.client.get("/api/org/enabled-departments")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["departmentIds"], [self.enabled_team.dept_id])

        update_response = self.client.put(
            "/api/org/enabled-departments",
            data=json.dumps({
                "departmentIds": [self.root.dept_id],
                "revision": 1,
                "orgRevision": 5,
            }),
            content_type="application/json",
        )
        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(update_response.json()["code"], "ENABLED_DEPARTMENTS_FORBIDDEN")

    def test_internal_directory_only_exposes_enabled_departments_and_members(self):
        PlatformEnabledDepartment.objects.create(department=self.root, enabled_by=self.admin.user_id)

        departments_response = self.internal_post(
            "/api/internal/org/departments/search",
            {"keyword": "", "limit": 100, "offset": 0},
        )
        users_response = self.internal_post(
            "/api/internal/org/users/search",
            {
                "keyword": "",
                "status": "active",
                "accountStatus": "enabled",
                "includeDepartments": True,
                "limit": 100,
                "offset": 0,
            },
        )

        self.assertEqual(departments_response.status_code, 200, departments_response.content)
        self.assertEqual(
            [item["deptId"] for item in departments_response.json()["items"]],
            [self.root.dept_id],
        )
        self.assertEqual(users_response.status_code, 200, users_response.content)
        self.assertEqual(
            [item["userId"] for item in users_response.json()["items"]],
            [self.root_member.user_id],
        )
        self.assertEqual(
            [item["deptId"] for item in users_response.json()["items"][0]["departments"]],
            [self.root.dept_id],
        )

    def test_organization_permissions_reject_disabled_department_targets(self):
        PlatformEnabledDepartment.objects.create(department=self.root, enabled_by=self.admin.user_id)
        OrganizationPermissionState.objects.update_or_create(
            state_id=1,
            defaults={"revision": 1, "rules": [], "manager_user_ids": []},
        )
        self.authenticate(self.admin)

        with patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id}):
            response = self.client.put(
                "/api/org/permissions",
                data=json.dumps({
                    "rules": [{
                        "scopeType": "department",
                        "targetId": str(self.disabled_team.dept_id),
                    }],
                    "revision": 1,
                    "orgRevision": 5,
                }),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "INVALID_ORGANIZATION_PERMISSION_RULE")

    def test_assigned_employee_can_manage_platform_settings_without_system_admin(self):
        PlatformEnabledDepartment.objects.bulk_create([
            PlatformEnabledDepartment(department=self.root, enabled_by=self.admin.user_id),
            PlatformEnabledDepartment(department=self.enabled_team, enabled_by=self.admin.user_id),
        ])
        OrganizationPermissionState.objects.update_or_create(
            state_id=1,
            defaults={
                "revision": 2,
                "rules": [{
                    "scopeType": "department",
                    "targetId": str(self.enabled_team.dept_id),
                    "targetName": self.enabled_team.name,
                    "sortOrder": 0,
                }],
                "manager_user_ids": [self.enabled_member.user_id],
            },
        )
        self.authenticate(self.enabled_member)

        response = self.client.get("/api/org/enabled-departments")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["departmentIds"], [1, 2])

        session_response = self.client.get("/api/auth/session/validate")
        self.assertEqual(session_response.status_code, 200, session_response.content)
        self.assertFalse(session_response.json()["canUseSystemAdmin"])
        self.assertTrue(session_response.json()["canManagePlatformSettings"])
        self.assertTrue(session_response.json()["canConfigurePermissions"])
        self.assertFalse(session_response.json()["canStartProxy"])

        permissions_response = self.client.get("/api/org/permissions")
        self.assertEqual(permissions_response.status_code, 200, permissions_response.content)
        self.assertEqual(
            permissions_response.json()["rules"][0]["permissionLabel"],
            "后台管理权限",
        )

        update_response = self.client.put(
            "/api/org/permissions",
            data=json.dumps({
                "rules": [{
                    "scopeType": "employee",
                    "targetId": self.enabled_member.user_id,
                }],
                "revision": 2,
                "orgRevision": 5,
            }),
            content_type="application/json",
        )
        self.assertEqual(update_response.status_code, 200, update_response.content)
        self.assertEqual(update_response.json()["revision"], 3)
        self.assertEqual(update_response.json()["memberUserIds"], [self.enabled_member.user_id])
