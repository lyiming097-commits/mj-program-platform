import json
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from identity_api.auth.session import create_auth_session_token
from identity_api.auth.tokens import AUTH_COOKIE_NAME
from identity_api.models import Employee, InternalServiceCredential, PlatformCompanyEntity, PlatformCompanyEntityHistory


class PlatformCompanyEntityTests(TestCase):
    base = "/api/directory/company-entities"

    def setUp(self):
        self.client.defaults["HTTP_SEC_FETCH_SITE"] = "same-origin"
        self.admin = Employee.objects.create(user_id="company-admin", name="主体管理员")
        self.operator = Employee.objects.create(user_id="company-operator", name="代理操作者")
        self.normal = Employee.objects.create(user_id="company-reader", name="普通员工")
        patcher = patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id, self.operator.user_id})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.login(self.admin)
        self.values = {"companyName": "测试平台公司", "taxNumber": "TEST-PLATFORM-TAX", "bankName": "测试银行",
                       "bankAccount": "TEST-ACCOUNT", "address": "测试地址", "phone": "0571-12345678"}
        self.secret = "test-platform-company-secret-0123456789"
        for service, app in (("crm-backend", "crm"), ("reader-backend", "reader")):
            credential = InternalServiceCredential(service_name=service, app_id=app)
            credential.set_secret(self.secret)
            credential.save()

    def login(self, employee, actor=None):
        self.client.cookies[AUTH_COOKIE_NAME] = create_auth_session_token(employee, actor_employee=actor)["token"]

    def create(self):
        response = self.client.post(self.base, json.dumps(self.values), content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["item"]

    def internal(self, suffix, payload, service="crm-backend", secret=None):
        return self.client.post(
            "/api/internal/directory/company-entities/" + suffix,
            json.dumps(payload), content_type="application/json",
            HTTP_X_INTERNAL_SERVICE=service, HTTP_X_INTERNAL_AUTH_SECRET=secret or self.secret,
        )

    def test_platform_crud_revision_audit_and_soft_delete(self):
        item = self.create()
        self.assertEqual(PlatformCompanyEntity.objects.get(pk=item["id"]).company_name, self.values["companyName"])
        self.assertEqual(PlatformCompanyEntityHistory.objects.count(), 1)
        values = {**self.values, "companyName": "更新后的平台公司", "revision": item["revision"]}
        url = f"{self.base}/{item['id']}"
        updated = self.client.put(url, json.dumps(values), content_type="application/json")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["item"]["revision"], 2)
        conflict = self.client.put(url, json.dumps(values), content_type="application/json")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "REVISION_CONFLICT")
        self.assertEqual(self.client.delete(url + "?revision=1").status_code, 409)
        self.assertEqual(self.client.delete(url + "?revision=2").status_code, 200)
        self.assertIsNotNone(PlatformCompanyEntity.objects.get(pk=item["id"]).deleted_at)
        self.assertEqual(self.internal("get", {"id": item["id"]}).status_code, 404)
        self.assertEqual(self.internal("search", {}).json()["total"], 0)
        self.assertEqual(list(PlatformCompanyEntityHistory.objects.values_list("action", flat=True)), ["create", "update", "delete"])

    def test_search_minimum_fields_and_profile_scope(self):
        item = self.create()
        for keyword in (self.values["companyName"], str(item["id"]), "ce shi ping tai gong si", "CSPTGS", self.values["taxNumber"].lower(), "platform-tax"):
            response = self.internal("search", {"keyword": keyword}, service="reader-backend")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["items"][0]["id"], item["id"])
            self.assertEqual(set(response.json()["items"][0]), {"id", "companyName", "pinyin", "pinyinInitials"})
        response = self.internal("profiles/search", {"keyword": "platform-tax"})
        self.assertEqual(response.json()["items"][0]["taxNumber"], self.values["taxNumber"])
        response = self.client.get(self.base, {"keyword": "platform-tax"})
        self.assertEqual(response.json()["items"][0]["id"], item["id"])
        response = self.internal("profiles/get", {"id": item["id"]})
        self.assertEqual(response.json()["item"]["bankAccount"], self.values["bankAccount"])
        response = self.internal("profiles/get", {"id": item["id"]}, service="reader-backend")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("item", response.json())
        response = self.internal("search", {}, secret="incorrect")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("items", response.json())

    def test_one_response_returns_more_than_a_page_without_deleted_entities(self):
        PlatformCompanyEntity.objects.bulk_create([
            PlatformCompanyEntity(company_name=f"全量目录公司{index:03}", tax_number=f"TEST-ALL-{index:03}")
            for index in range(121)
        ])
        PlatformCompanyEntity.objects.create(company_name="已删除公司", tax_number="TEST-DELETED", deleted_at=timezone.now())
        page = self.internal("search", {}).json()
        self.assertEqual((page["count"], page["total"]), (20, 121))
        self.assertFalse(page["all"])
        for suffix, service in (("search", "reader-backend"), ("profiles/search", "crm-backend")):
            response = self.internal(suffix, {"all": True}, service=service)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual((data["count"], data["total"]), (121, 121))
            self.assertEqual(len(data["items"]), 121)
            self.assertTrue(data["all"])
            self.assertNotIn("offset", data)
            self.assertNotIn("limit", data)
            self.assertEqual(data["directoryRevision"], page["directoryRevision"])
            self.assertNotIn("TEST-DELETED", json.dumps(data))
            if service == "reader-backend":
                self.assertTrue(all(set(item) == {"id", "companyName", "pinyin", "pinyinInitials"} for item in data["items"]))
        management = self.client.get(self.base, {"all": "true"}).json()
        self.assertEqual(management["count"], 121)
        self.assertEqual(management["directoryRevision"], page["directoryRevision"])
        filtered = self.internal("search", {"all": True, "keyword": "test-all-120"}).json()
        self.assertEqual(filtered["count"], 1)
        empty = self.internal("search", {"all": True, "keyword": "does-not-exist"}).json()
        self.assertEqual((empty["total"], empty["count"], empty["items"]), (0, 0, []))
        self.assertEqual(self.internal("profiles/search", {"all": True}, service="reader-backend").status_code, 403)
        self.assertEqual(self.internal("search", {"all": True}, secret="incorrect").status_code, 403)

    def test_management_denies_non_admin_and_uses_effective_proxy_identity(self):
        self.create()
        self.login(self.normal)
        self.assertEqual(self.client.get(self.base).status_code, 403)
        self.assertEqual(self.client.post(self.base, json.dumps(self.values), content_type="application/json").status_code, 403)
        self.login(self.normal, actor=self.admin)
        self.assertEqual(self.client.get(self.base).status_code, 403)
        self.login(self.admin, actor=self.operator)
        self.assertEqual(self.client.get(self.base).status_code, 200)
        self.values["taxNumber"] = "TEST-PROXY-TAX"
        item = self.create()
        history = PlatformCompanyEntityHistory.objects.get(entity_id=item["id"])
        self.assertEqual(history.actor_user_id, self.operator.user_id)
        self.assertEqual(history.effective_user_id, self.admin.user_id)

    def test_directory_paging_revision_and_invalid_requests(self):
        item = self.create()
        initial = self.internal("search", {"limit": 1}).json()
        self.client.put(f"{self.base}/{item['id']}", json.dumps({**self.values, "companyName": "主体已改名", "revision": 1}), content_type="application/json")
        response = self.internal("search", {"limit": 1, "offset": 1, "directoryRevision": initial["directoryRevision"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.internal("search", {"all": True, "directoryRevision": initial["directoryRevision"]}).status_code, 409)
        for payload in ({"limit": True}, {"limit": 1.5}, {"limit": 101}, {"offset": -1}, [], {"keyword": {}},
                        {"all": None}, {"all": 1}, {"all": []}, {"all": "yes"}, {"all": True, "offset": 0}, {"all": True, "limit": 100}):
            self.assertEqual(self.internal("search", payload).status_code, 400)
        for entity_id in (None, True, "17.0", 0, 10**30):
            self.assertEqual(self.internal("get", {"id": entity_id}).status_code, 400)
        self.assertEqual(self.internal("get", {"id": "99999"}).status_code, 404)
        self.assertEqual(self.client.get("/api/internal/directory/company-entities/search").status_code, 405)

    def test_duplicate_tax_number_and_cross_origin_writes_are_rejected(self):
        self.create()
        response = self.client.post(self.base, json.dumps(self.values), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlatformCompanyEntity.objects.count(), 1)
        response = self.client.post(self.base, json.dumps(self.values), content_type="application/json", HTTP_SEC_FETCH_SITE="cross-site")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "CROSS_ORIGIN_WRITE_BLOCKED")
