import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from . import views
from .models import AppPermissionRule, WorkflowCase


class WorkflowCaseApiRetirementTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        AppPermissionRule.objects.all().delete()

    def employee_request(self, *, admin: bool):
        request = self.factory.get("/api/after-sales/employees/directory")
        request.auth_user_id = "directory-user"
        request.auth_user_name = "目录用户"
        request.auth_actor_user_id = "directory-user"
        request.auth_actor_name = "目录用户"
        request.auth_is_proxy = False
        request.auth_can_use_system_admin = admin
        return request

    def test_case_urls_are_not_registered(self):
        retired_paths = (
            "/api/after-sales/cases",
            "/api/after-sales/cases/handlers",
            "/api/after-sales/cases/1/advance",
            "/api/after-sales/cases/1/return",
        )
        for path in retired_paths:
            with self.subTest(path=path):
                with self.assertRaises(Resolver404):
                    resolve(path)

        retired_names = (
            "cases",
            "case-handler-directory",
            "case-advance",
            "case-return",
        )
        for name in retired_names:
            with self.subTest(name=name):
                with self.assertRaises(NoReverseMatch):
                    kwargs = {"case_id": 1} if name in {"case-advance", "case-return"} else None
                    reverse(name, kwargs=kwargs)

    def test_employee_directory_moved_out_of_case_namespace(self):
        match = resolve("/api/after-sales/employees/directory")

        self.assertEqual(match.url_name, "employee-directory")
        self.assertEqual(reverse("employee-directory"), "/api/after-sales/employees/directory")

    @patch("after_sales_api.views.get_auth_organization_snapshot")
    def test_employee_directory_is_available_to_management_users_and_keeps_active_staff_lookup(self, organization):
        organization.return_value = (
            [
                {
                    "deptId": 10,
                    "name": "产品组",
                    "pinyinInitials": "cpz",
                },
            ],
            [
                {
                    "userId": "active-user",
                    "rawName": "在职人员",
                    "avatarUrl": "https://example.test/avatar.png",
                    "pinyinInitials": "zzry",
                    "departmentIds": [10],
                    "status": "active",
                    "accountStatus": "enabled",
                },
                {
                    "userId": "left-user",
                    "rawName": "离职人员",
                    "status": "inactive",
                    "accountStatus": "enabled",
                },
            ],
            9,
        )

        denied = views.employee_directory(self.employee_request(admin=False))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(json.loads(denied.content)["code"], "APP_ACCESS_DENIED")
        organization.assert_not_called()
        AppPermissionRule.objects.create(permission="sales", scope_type="employee", target_id="directory-user")
        available = views.employee_directory(self.employee_request(admin=False))

        self.assertEqual(available.status_code, 200)
        self.assertEqual(json.loads(available.content), {
            "items": [{
                "userId": "active-user",
                "name": "在职人员",
                "avatarUrl": "https://example.test/avatar.png",
                "pinyin": "",
                "pinyinInitials": "zzry",
                "departments": [{
                    "deptId": "10",
                    "name": "产品组",
                    "pinyin": "",
                    "pinyinInitials": "cpz",
                    "departmentPathText": "",
                }],
            }],
            "orgRevision": 9,
        })
        organization.assert_called_once()

        organization.reset_mock()
        allowed = views.employee_directory(self.employee_request(admin=True))

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(json.loads(allowed.content), {
            "items": [{
                "userId": "active-user",
                "name": "在职人员",
                "avatarUrl": "https://example.test/avatar.png",
                "pinyin": "",
                "pinyinInitials": "zzry",
                "departments": [{
                    "deptId": "10",
                    "name": "产品组",
                    "pinyin": "",
                    "pinyinInitials": "cpz",
                    "departmentPathText": "",
                }],
            }],
            "orgRevision": 9,
        })

    def test_historical_case_records_remain_available_to_the_data_layer(self):
        historical = WorkflowCase.objects.create(
            code="HISTORICAL-CASE-1",
            case_type=WorkflowCase.TYPE_SUPPORT,
            title="历史求助事项",
            applicant_user_id="historical-user",
            content="仅保留历史数据，不再提供 HTTP 接口。",
        )

        self.assertEqual(WorkflowCase.objects.get(pk=historical.pk).title, "历史求助事项")
