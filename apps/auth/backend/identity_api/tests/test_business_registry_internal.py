import copy
import json
import uuid
from unittest.mock import patch

import requests
from django.test import TestCase, override_settings

from identity_api.auth.session import create_auth_session_token
from identity_api.auth.tokens import AUTH_COOKIE_NAME
from identity_api.models import (
    BusinessRegistryCompany, BusinessRegistryQuery, BusinessRegistryQueryCompany,
    Employee, InternalServiceCredential,
)


BASE = "/api/internal/business-registry"
PUBLIC_BASE = "/api/org/business-registry"
SECRET = "test-internal-registry-secret-0123456789"
COMPANY = {
    "companyName": "内部接口测试企业", "creditNo": "TEST-CREDIT-001", "companyCode": "TEST-REG-001",
    "legalPerson": "测试法人", "companyStatus": "存续", "establishDate": "20260101",
}


def success(companies=None, page=1, total=21):
    return (200, {"success": True, "code": 200, "data": {
        "companyList": [copy.deepcopy(COMPANY)] if companies is None else companies,
        "orderNo": "provider-order-private",
        "pageInfo": {"pageIndex": page, "totalRecords": total},
    }}, "provider-gateway-private")


@override_settings(BUSINESS_REGISTRY_APPCODE="test-appcode-not-real")
class InternalBusinessRegistryTests(TestCase):
    def setUp(self):
        for app in ("crm", "cable-mall"):
            credential = InternalServiceCredential(service_name=f"{app}-backend", app_id=app)
            credential.set_secret(SECRET + app)
            credential.save()
        self.member = Employee.objects.create(user_id="registry-member", name="普通员工")
        self.other = Employee.objects.create(user_id="registry-other", name="另一员工")
        self.admin = Employee.objects.create(user_id="registry-admin", name="管理员")
        whitelist = patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id})
        whitelist.start()
        self.addCleanup(whitelist.stop)
        provider = patch("identity_api.org.business_registry.query_company_service", return_value=success())
        self.provider = provider.start()
        self.addCleanup(provider.stop)

    def headers(self, app="crm"):
        return {"HTTP_X_INTERNAL_SERVICE": f"{app}-backend", "HTTP_X_INTERNAL_AUTH_SECRET": SECRET + app}

    def token(self, employee=None, actor=None):
        return create_auth_session_token(employee or self.member, actor_employee=actor)["token"]

    def search(self, app="crm", **values):
        payload = {"keyword": "测试", "queryRequestId": str(uuid.uuid4()), **values}
        return self.client.post(BASE + "/search", json.dumps(payload), content_type="application/json", **self.headers(app))

    def detail(self, query_request_id, app="crm", **values):
        return self.client.post(BASE + "/queries/get", json.dumps({"queryRequestId": query_request_id, **values}),
            content_type="application/json", **self.headers(app))

    def test_service_credential_required_even_with_valid_admin_cookie(self):
        self.client.cookies[AUTH_COOKIE_NAME] = self.token(self.admin)
        cases = [
            ({}, "MISSING_INTERNAL_SERVICE"),
            ({"HTTP_X_INTERNAL_SERVICE": "unregistered-backend"}, "UNKNOWN_INTERNAL_SERVICE"),
            ({"HTTP_X_INTERNAL_SERVICE": "crm-backend"}, "INVALID_INTERNAL_SECRET"),
            ({**self.headers(), "HTTP_X_INTERNAL_AUTH_SECRET": "wrong"}, "INVALID_INTERNAL_SECRET"),
            ({**self.headers(), "HTTP_X_INTERNAL_SERVICE": "cable-mall-backend"}, "INVALID_INTERNAL_SECRET"),
        ]
        for endpoint in ("/search", "/queries/get"):
            for headers, code in cases:
                with self.subTest(endpoint=endpoint, code=code):
                    response = self.client.post(BASE + endpoint, "{}", content_type="application/json", **headers)
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.json()["code"], code)
        InternalServiceCredential.objects.filter(app_id="crm").update(enabled=False)
        self.assertEqual(self.search().json()["code"], "INTERNAL_SERVICE_DISABLED")
        self.provider.assert_not_called()
        self.assertFalse(BusinessRegistryQuery.objects.exists())

    def test_search_returns_only_enterprise_name_and_credit_no_and_saves_the_full_page(self):
        rows = [{**COMPANY, "companyName": f"测试企业 {index}", "creditNo": f"TEST-CREDIT-{index}"} for index in range(20)]
        rows[-1]["creditNo"] = ""
        self.provider.return_value = success(rows)
        response = self.search(sourceAppId="forged", actorUserId="forged")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["requestId"], response["X-Request-Id"])
        self.assertTrue(data["hasMore"])
        self.assertEqual(data["nextPageNum"], 2)
        self.assertEqual(data["companies"], [{"companyName": row["companyName"], "creditNo": row["creditNo"]} for row in rows])
        self.assertEqual(data["companies"][-1]["creditNo"], "", "registration number must not replace a missing unified social credit code")
        self.assertEqual(BusinessRegistryCompany.objects.count(), 20)
        self.assertEqual(BusinessRegistryQueryCompany.objects.count(), 20)
        record = BusinessRegistryQuery.objects.get()
        self.assertEqual(record.companies, rows)
        self.assertEqual((record.source_app_id, record.source_service), ("crm", "crm-backend"))
        self.assertEqual((record.actor_user_id, record.effective_user_id), ("", ""))
        self.assertEqual(record.actor_name, "crm-backend")
        for private in ("provider-order-private", "provider-gateway-private", "测试法人", "test-appcode-not-real"):
            self.assertNotIn(private, json.dumps(data, ensure_ascii=False))

    def test_retries_reuse_a_query_and_cannot_change_conditions_or_caller(self):
        key = str(uuid.uuid4())
        first = self.search(queryRequestId=key).json()
        second = self.search(queryRequestId=key).json()
        self.assertEqual(first["queryId"], second["queryId"])
        self.assertEqual(first["companies"], self.detail(key).json()["companies"])
        for changed in ({"keyword": "其他词"}, {"pageNum": 2}, {"pageSize": 10}, {"app": "cable-mall"}, {"token": self.token()}):
            self.assertEqual(self.search(queryRequestId=key, **changed).status_code, 409)
        self.assertEqual(self.detail(key, app="cable-mall").status_code, 404)
        self.assertEqual(self.detail(key, token=self.token()).status_code, 404)
        self.provider.assert_called_once()
        self.assertEqual(BusinessRegistryQuery.objects.count(), 1)

    def test_each_page_is_explicit_and_has_its_own_history(self):
        first = self.search().json()
        self.assertEqual(self.provider.call_count, 1)
        self.provider.return_value = success(page=2)
        second = self.search(pageNum=2).json()
        self.assertFalse(second["hasMore"])
        self.assertIsNone(second["nextPageNum"])
        self.assertNotEqual(first["queryRequestId"], second["queryRequestId"])
        self.assertEqual(BusinessRegistryCompany.objects.count(), 1)
        self.assertEqual(BusinessRegistryQueryCompany.objects.count(), 2)
        self.assertEqual(self.provider.call_count, 2)
        self.provider.return_value = success(page=100, total=3000)
        self.assertFalse(self.search(pageNum=100).json()["hasMore"])

    def test_unknown_totals_and_empty_pages_stop_pagination(self):
        self.provider.return_value = success([COMPANY] * 20, total=None)
        self.assertTrue(self.search().json()["hasMore"])
        self.provider.return_value = success([COMPANY], total=None)
        self.assertFalse(self.search().json()["hasMore"])
        self.provider.return_value = success([], total=100)
        result = self.search().json()
        self.assertEqual(result["status"], "empty")
        self.assertFalse(result["hasMore"])

    def test_human_identity_is_validated_and_proxy_attribution_is_preserved(self):
        token = self.token(actor=self.admin)
        result = self.search(token=token, actorUserId="fake").json()
        record = BusinessRegistryQuery.objects.get()
        self.assertEqual((record.actor_user_id, record.actor_name), (self.admin.user_id, self.admin.name))
        self.assertEqual((record.effective_user_id, record.effective_name), (self.member.user_id, self.member.name))
        self.assertEqual(self.detail(result["queryRequestId"], token=token).status_code, 200)
        self.assertEqual(self.detail(result["queryRequestId"]).status_code, 404)
        self.assertEqual(self.detail(result["queryRequestId"], token=self.token(self.other)).status_code, 404)
        self.assertEqual(self.provider.call_count, 1)

    def test_invalid_or_disabled_user_token_is_not_downgraded_to_a_machine_call(self):
        self.assertEqual(self.search(token="invalid").status_code, 401)
        token = self.token()
        self.member.account_status = Employee.ACCOUNT_DISABLED
        self.member.save(update_fields=["account_status"])
        self.assertEqual(self.search(token=token).status_code, 403)
        self.provider.assert_not_called()

    def test_running_query_can_be_polled_without_calling_provider(self):
        key = uuid.uuid4()
        BusinessRegistryQuery.objects.create(request_id=key, source_app_id="crm", source_service="crm-backend",
            keyword="测试", page_num=1, page_size=20, actor_user_id="", effective_user_id="",
            actor_name="crm-backend", effective_name="crm-backend")
        for response in (self.search(queryRequestId=str(key)), self.detail(str(key))):
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["status"], "running")
            self.assertEqual(response.json()["companies"], [])
            self.assertFalse(response.json()["hasMore"])
        self.provider.assert_not_called()

    def test_failed_requests_are_recorded_and_never_automatically_retried(self):
        self.provider.side_effect = requests.Timeout("sensitive transport details")
        key = str(uuid.uuid4())
        first = self.search(queryRequestId=key).json()
        self.assertEqual(first["status"], "failed")
        self.assertEqual(first["companies"], [])
        self.assertFalse(first["hasMore"])
        self.assertNotIn("sensitive", first["message"])
        self.assertEqual(self.search(queryRequestId=key).json()["status"], "failed")
        self.assertEqual(self.detail(key).json()["status"], "failed")
        self.provider.assert_called_once()

    def test_input_validation_rejects_malformed_requests_before_any_paid_call(self):
        for values in ({"keyword": ""}, {"keyword": "x" * 201}, {"keyword": 123}, {"pageNum": 0},
                       {"pageNum": 101}, {"pageNum": True}, {"pageSize": 21}, {"pageSize": 0},
                       {"queryRequestId": "invalid"}, {"token": ""}, {"token": {"sub": "admin"}}):
            with self.subTest(values=values):
                self.assertEqual(self.search(**values).status_code, 400)
        for raw in ("[]", "not json", "null"):
            self.assertEqual(self.client.post(BASE + "/search", raw, content_type="application/json", **self.headers()).status_code, 400)
        self.assertEqual(self.detail("invalid").status_code, 400)
        self.assertEqual(self.detail(str(uuid.uuid4())).status_code, 404)
        self.assertEqual(self.client.get(BASE + "/search", **self.headers()).status_code, 405)
        self.assertEqual(self.client.get(BASE + "/queries/get", **self.headers()).status_code, 405)
        self.provider.assert_not_called()

    def test_existing_snapshots_remain_readable_when_provider_is_unconfigured(self):
        key = str(uuid.uuid4())
        self.search(queryRequestId=key)
        with override_settings(BUSINESS_REGISTRY_APPCODE=""):
            self.assertEqual(self.search().status_code, 503)
            self.assertEqual(self.search(queryRequestId=key).status_code, 200)
            self.assertEqual(self.detail(key).status_code, 200)
        self.provider.assert_called_once()

    def test_admin_history_includes_internal_queries_but_request_ids_do_not_cross_channels(self):
        token = self.token(self.admin)
        key = str(uuid.uuid4())
        self.search(queryRequestId=key, token=token)
        self.client.cookies[AUTH_COOKIE_NAME] = token
        response = self.client.get(PUBLIC_BASE + "/queries").json()
        self.assertEqual(response["items"][0]["sourceAppId"], "crm")
        self.assertEqual(response["items"][0]["actorUserId"], self.admin.user_id)
        self.assertEqual(self.client.post(PUBLIC_BASE + "/search", json.dumps({"keyword": "测试", "requestId": key}),
            content_type="application/json", HTTP_SEC_FETCH_SITE="same-origin").status_code, 409)
        self.client.cookies[AUTH_COOKIE_NAME] = self.token()
        self.assertEqual(self.client.get(PUBLIC_BASE + "/companies").status_code, 403)
        self.provider.assert_called_once()

    def test_exact_cached_lookup_is_read_only_and_hides_query_ownership(self):
        self.search()
        self.provider.reset_mock()
        data = {"keywords": [COMPANY["companyName"], "内部接口", COMPANY["creditNo"]]}
        response = self.client.post(BASE + "/companies/cached", json.dumps(data), content_type="application/json", **self.headers())
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["paidQueries"], 0)
        self.assertEqual(len(result["items"][0]["companies"]), 1)
        self.assertEqual(result["items"][1]["companies"], [])
        self.assertEqual(len(result["items"][2]["companies"]), 1)
        allowed = {"companyName", "creditNo", "evidenceId", "queriedAt"}
        self.assertEqual(set(result["items"][0]["companies"][0]), allowed)
        self.assertEqual(BusinessRegistryQuery.objects.count(), 1)
        self.provider.assert_not_called()
        self.assertEqual(self.client.post(BASE + "/companies/cached", json.dumps(data), content_type="application/json").status_code, 403)
        for keywords in ([], [""], ["x"] * 101, "x", [123]):
            self.assertEqual(self.client.post(BASE + "/companies/cached", json.dumps({"keywords": keywords}),
                content_type="application/json", **self.headers()).status_code, 400)
