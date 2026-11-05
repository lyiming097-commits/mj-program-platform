import json

from django.test import TestCase
from django.utils import timezone

from identity_api.models import Department, Employee, InternalServiceCredential


class DepartureHistoryTests(TestCase):
    def setUp(self):
        self.secret = "test-departure-history-secret-123456789"
        for app_id in ("crm", "another-app"):
            credential = InternalServiceCredential(service_name=f"{app_id}-backend", app_id=app_id)
            credential.set_secret(self.secret)
            credential.save()
        self.recorded = timezone.now()
        self.departed = Employee.objects.create(
            user_id="departed", name="离职销售", status=Employee.STATUS_INACTIVE,
            former_dingtalk_departments=[{"deptId": 10, "name": "原业务组", "pathText": "公司 / 原业务组"}],
            former_organization_recorded_at=self.recorded,
        )
        Department.objects.create(dept_id=10, name="合并后的部门")
        Employee.objects.create(user_id="active", name="在职销售", former_dingtalk_departments=[{"name": "旧记录"}])

    def post(self, data, service="crm-backend", secret=None):
        return self.client.post("/api/internal/org/users/departure-history", json.dumps(data),
                                content_type="application/json", HTTP_X_INTERNAL_SERVICE=service,
                                HTTP_X_INTERNAL_AUTH_SECRET=self.secret if secret is None else secret)

    def test_snapshots_survive_department_renames_and_removed_memberships(self):
        response = self.post({"userIds": ["departed", "active", "missing", "departed"]})
        self.assertEqual(response.status_code, 200)
        self.assertIn("orgRevision", response.json())
        departed, active, missing = response.json()["items"]
        self.assertEqual(departed["formerDingTalkDepartments"][0]["name"], "原业务组")
        self.assertEqual(departed["formerOrganizationRecordedAt"], self.recorded.isoformat())
        self.assertEqual(departed["pinyin"], "lizhixiaoshou")
        self.assertEqual(departed["pinyinInitials"], "lzxs")
        self.assertEqual(active["status"], "在职")
        self.assertNotIn("formerDingTalkDepartments", active)
        self.assertEqual(active["pinyin"], "zaizhixiaoshou")
        self.assertEqual(missing, {"userId": "missing", "found": False})
        self.assertNotIn("accountStatus", departed)
        self.departed.refresh_from_db()
        self.assertEqual(self.departed.former_organization_recorded_at, self.recorded)

    def test_credentials_and_crm_service_restriction(self):
        self.assertEqual(self.post({"userIds": ["departed"]}, service="another-app-backend").status_code, 403)
        self.assertEqual(self.post({"userIds": ["departed"]}, secret="wrong").status_code, 403)
        self.assertEqual(self.client.get("/api/internal/org/users/departure-history").status_code, 405)

    def test_no_enumeration_and_batch_limits(self):
        self.assertEqual(self.post({}).status_code, 400)
        self.assertEqual(self.post({"userIds": []}).json()["items"], [])
        self.assertEqual(self.post({"userIds": ["departed"] * 501}).status_code, 400)
