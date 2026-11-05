from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from identity_api.dingtalk.client import DingTalkAPIError
from identity_api.models import (
    Department, DepartmentEmployee, Employee, OrganizationState,
)
from identity_api.org.sync import (
    _list_department_users,
    _validate_snapshot_size,
    _validate_user_detail_errors,
    sync_organization_contacts,
)


class OrganizationSyncSafetyTests(SimpleTestCase):
    def test_empty_snapshot_is_rejected(self):
        with self.assertRaises(DingTalkAPIError):
            _validate_snapshot_size(
                previous_department_count=0,
                previous_employee_count=0,
                previous_membership_count=0,
                department_count=1,
                employee_count=0,
                membership_count=0,
            )

    def test_abnormal_employee_drop_is_rejected(self):
        with self.assertRaises(DingTalkAPIError):
            _validate_snapshot_size(
                previous_department_count=80,
                previous_employee_count=200,
                previous_membership_count=230,
                department_count=80,
                employee_count=100,
                membership_count=220,
            )

    @patch("identity_api.org.sync._request_topapi_result")
    def test_repeated_employee_cursor_is_rejected(self, request_result):
        request_result.return_value = {
            "list": [{"userid": "one"}],
            "has_more": True,
            "next_cursor": 0,
        }
        with self.assertRaises(DingTalkAPIError):
            _list_department_users("token", 1)

    def test_excessive_user_detail_errors_are_rejected(self):
        with patch.dict(
            "os.environ",
            {"DINGTALK_ORG_SYNC_MAX_USER_DETAIL_ERROR_RATIO": "0.05"},
            clear=False,
        ):
            with self.assertRaises(DingTalkAPIError):
                _validate_user_detail_errors(error_count=2, employee_count=20)


class OrganizationSyncDataQualityTests(TestCase):
    def test_resignation_records_former_dingtalk_organization_once_and_rehire_resets_it(self):
        Department.objects.create(dept_id=1, name="旧公司")
        team = Department.objects.create(dept_id=2, name="旧研发", parent_dept_id=1)
        employee = Employee.objects.create(user_id="u1", name="张三")
        DepartmentEmployee.objects.create(department=team, employee=employee)
        def sync(active, team_name):
            def department_detail(_token, dept_id):
                return {
                    "dept_id": dept_id,
                    "name": "新公司" if dept_id == 1 else team_name,
                    "parent_id": None if dept_id == 1 else 1,
                }

            with (
                patch("identity_api.org.sync._get_app_access_token", return_value="token"),
                patch("identity_api.org.sync._get_department_detail", side_effect=department_detail),
                patch("identity_api.org.sync._list_sub_departments", side_effect=lambda _token, dept_id: [{"dept_id": 2}] if dept_id == 1 else []),
                patch("identity_api.org.sync._list_department_users", side_effect=lambda _token, dept_id: [{"userid": "u1", "name": "张三"}] if dept_id == 2 else []),
                patch("identity_api.org.sync._get_user_detail_by_userid", return_value={"userid": "u1", "name": "张三", "active": active}),
            ):
                sync_organization_contacts()
            employee.refresh_from_db()

        sync(False, "新研发")
        self.assertEqual(employee.status, Employee.STATUS_INACTIVE)
        self.assertEqual(employee.former_dingtalk_departments[0]["pathText"], "旧公司 / 旧研发")
        recorded_at = employee.former_organization_recorded_at

        sync(False, "再改名")
        self.assertEqual(employee.former_dingtalk_departments[0]["pathText"], "旧公司 / 旧研发")
        self.assertEqual(employee.former_organization_recorded_at, recorded_at)

        sync(True, "再改名")
        self.assertEqual(employee.former_dingtalk_departments, [])
        self.assertIsNone(employee.former_organization_recorded_at)

        sync(False, "再次离职")
        self.assertEqual(employee.former_dingtalk_departments[0]["pathText"], "新公司 / 再改名")
        self.assertIsNotNone(employee.former_organization_recorded_at)

    def test_existing_inactive_employee_has_no_invented_history(self):
        employee = Employee.objects.create(user_id="former", name="已离职", status=Employee.STATUS_INACTIVE)
        self.assertEqual(employee.former_dingtalk_departments, [])
        self.assertIsNone(employee.former_organization_recorded_at)

    def test_new_employee_detail_failure_rejects_snapshot(self):
        department = Department.objects.create(dept_id=1, name="原部门")
        employee = Employee.objects.create(user_id="u1", name="原姓名")
        DepartmentEmployee.objects.create(department=department, employee=employee)

        with (
            patch("identity_api.org.sync._get_app_access_token", return_value="token"),
            patch(
                "identity_api.org.sync._get_department_detail",
                return_value={"dept_id": 1, "name": "不应保存的新部门名", "parent_id": None},
            ),
            patch("identity_api.org.sync._list_sub_departments", return_value=[]),
            patch(
                "identity_api.org.sync._list_department_users",
                return_value=[
                    {"userid": "u1", "name": "原姓名"},
                    {"userid": "u2", "name": "降级的新员工"},
                ],
            ),
            patch(
                "identity_api.org.sync._get_user_detail_by_userid",
                side_effect=[{"userid": "u1", "name": "原姓名"}, DingTalkAPIError("temporary detail failure")],
            ),
            patch.dict(
                "os.environ",
                {"DINGTALK_ORG_SYNC_MAX_USER_DETAIL_ERROR_RATIO": "1"},
                clear=False,
            ),
        ):
            with self.assertRaises(DingTalkAPIError):
                sync_organization_contacts()

        department.refresh_from_db()
        self.assertEqual(department.name, "原部门")
        self.assertFalse(Employee.objects.filter(user_id="u2").exists())
        self.assertEqual(OrganizationState.objects.get(state_id=1).revision, 0)

    def test_small_detail_failure_keeps_existing_employee_profile(self):
        department = Department.objects.create(dept_id=1, name="原部门")
        employee = Employee.objects.create(
            user_id="u1",
            name="原姓名",
            avatar_url="https://example.com/original.png",
        )
        DepartmentEmployee.objects.create(department=department, employee=employee)

        with (
            patch("identity_api.org.sync._get_app_access_token", return_value="token"),
            patch(
                "identity_api.org.sync._get_department_detail",
                return_value={"dept_id": 1, "name": "新部门", "parent_id": None},
            ),
            patch("identity_api.org.sync._list_sub_departments", return_value=[]),
            patch(
                "identity_api.org.sync._list_department_users",
                return_value=[{"userid": "u1", "name": "降级姓名"}],
            ),
            patch(
                "identity_api.org.sync._get_user_detail_by_userid",
                side_effect=DingTalkAPIError("temporary detail failure"),
            ),
            patch.dict(
                "os.environ",
                {"DINGTALK_ORG_SYNC_MAX_USER_DETAIL_ERROR_RATIO": "1"},
                clear=False,
            ),
        ):
            result = sync_organization_contacts()

        employee.refresh_from_db()
        self.assertEqual(employee.name, "原姓名")
        self.assertEqual(employee.avatar_url, "https://example.com/original.png")
        self.assertEqual(result["userDetailFallbackCount"], 1)
        self.assertEqual(result["orgRevision"], 1)
        self.assertEqual(OrganizationState.objects.get(state_id=1).revision, 1)
