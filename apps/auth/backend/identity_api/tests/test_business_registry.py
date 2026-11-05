import copy
import json
import uuid
from datetime import datetime
from importlib import import_module
from unittest.mock import MagicMock, patch

import requests
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, SimpleTestCase, TransactionTestCase, override_settings

from identity_api.auth.session import create_auth_session_token
from identity_api.auth.tokens import AUTH_COOKIE_NAME
from identity_api.models import (
    BusinessRegistryCompany, BusinessRegistryQuery, BusinessRegistryQueryCompany, Department, DepartmentEmployee,
    Employee, OrganizationPermissionState, PlatformDepartmentState, PlatformEnabledDepartment,
)
from identity_api.org.business_registry import complete_query
from identity_api.org.business_registry_client import identity_key, query_company_service, QUERY_URL


BASE = "/api/org/business-registry"
COMPANY = {
    "companyName": "工商接口测试企业", "creditNo": "TEST-CREDIT-001", "companyCode": "TEST-REG-001",
    "legalPerson": "测试法人", "companyStatus": "在营（开业）", "establishDate": "20130306",
}


def success(rows=None, page=1):
    return (200, {"success": True, "code": 200, "msg": "成功", "data": {
        "orderNo": "test-order", "companyList": [copy.deepcopy(COMPANY)] if rows is None else rows,
        "pageInfo": {"totalRecords": "21", "pageIndex": str(page), "pageSize": "20"},
    }}, "test-gateway")


@override_settings(BUSINESS_REGISTRY_APPCODE="test-only-appcode")
class BusinessRegistryTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_SEC_FETCH_SITE"] = "same-origin"
        self.admin = Employee.objects.create(user_id="admin", name="测试管理员")
        self.member = Employee.objects.create(user_id="member", name="测试成员")
        self.actor = Employee.objects.create(user_id="actor", name="测试操作者")
        whitelist = patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {"admin", "actor"})
        whitelist.start()
        self.addCleanup(whitelist.stop)
        provider = patch("identity_api.org.business_registry.query_company_service", return_value=success())
        self.provider = provider.start()
        self.addCleanup(provider.stop)
        self.authenticate(self.admin)

    def authenticate(self, user, actor=None):
        self.client.cookies[AUTH_COOKIE_NAME] = create_auth_session_token(user, actor_employee=actor)["token"]

    def search(self, **changes):
        payload = {"keyword": "测试", "pageNum": 1, "pageSize": 20, "requestId": str(uuid.uuid4()), **changes}
        return self.client.post(BASE + "/search", json.dumps(payload), content_type="application/json")

    def test_search_persists_companies_and_immutable_snapshots_without_requery_on_read(self):
        first = self.search().json()
        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(first["totalRecords"], 21)
        self.assertEqual(first["companies"], [COMPANY])
        record = BusinessRegistryQuery.objects.get()
        self.assertEqual(record.response_payload["data"]["orderNo"], "test-order")
        self.assertEqual(record.gateway_request_id, "test-gateway")
        changed = {**COMPANY, "legalPerson": "变更后的法人", "companyName": "变更后的企业名称"}
        self.provider.return_value = success([changed])
        second = self.search().json()
        self.assertEqual(BusinessRegistryCompany.objects.count(), 1)
        company = BusinessRegistryCompany.objects.get()
        self.assertEqual(company.legal_person, "变更后的法人")
        self.assertEqual(company.last_query_id, second["id"])
        self.assertEqual(self.client.get(BASE + f'/queries/{first["id"]}').json()["companies"], [COMPANY])
        self.assertEqual(self.client.get(BASE + "/companies", {"keyword": "TEST-CREDIT"}).json()["total"], 1)
        self.assertEqual(self.client.get(BASE + "/companies", {"keyword": "变更后"}).json()["total"], 1)
        self.assertEqual(self.client.get(BASE + "/companies", {"keyword": "不存在"}).json()["total"], 0)
        self.assertEqual(self.client.get(BASE + "/queries").json()["total"], 2)
        self.assertEqual(self.provider.call_count, 2)

    def test_same_request_id_never_calls_provider_twice(self):
        request_id = str(uuid.uuid4())
        first = self.search(requestId=request_id).json()
        second = self.search(requestId=request_id).json()
        self.assertEqual(first, second)
        self.assertEqual(self.search(requestId=request_id, keyword="另一个关键词").status_code, 409)
        self.assertEqual(BusinessRegistryQuery.objects.count(), 1)
        self.assertEqual(BusinessRegistryQueryCompany.objects.count(), 1)
        self.provider.assert_called_once_with("test-only-appcode", "测试", 1, 20)

    def test_running_request_is_not_repeated(self):
        record = BusinessRegistryQuery.objects.create(request_id=uuid.uuid4(), keyword="测试", page_num=1, page_size=20,
            actor_user_id="admin", actor_name="管理员", effective_user_id="admin", effective_name="管理员")
        response = self.search(requestId=str(record.request_id))
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "running")
        self.provider.assert_not_called()

    def test_failures_empty_and_http_errors_are_recorded_without_overwriting_companies(self):
        self.search()
        cases = [
            ((200, {"success": False, "code": 400, "msg": "查无数据", "data": None}, ""), "empty"),
            ((200, {"success": False, "code": 400, "msg": "参数错误"}, ""), "failed"),
            ((403, {"message": "invalid authentication"}, ""), "failed"),
            ((200, {"success": True, "code": 200, "data": None}, ""), "failed"),
            ((200, {}, ""), "failed"),
        ]
        for provider_result, expected in cases:
            with self.subTest(provider_result=provider_result):
                self.provider.return_value = provider_result
                result = self.search().json()
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["companies"], [])
        self.provider.side_effect = requests.Timeout("must not expose transport details")
        result = self.search().json()
        self.assertEqual(result["status"], "failed")
        self.assertIn("超时", result["message"])
        self.assertNotIn("transport", json.dumps(result))
        self.assertEqual(BusinessRegistryCompany.objects.count(), 1)
        self.assertEqual(BusinessRegistryQuery.objects.count(), 7)
        self.assertEqual(self.provider.call_count, 7)

    def test_null_optional_fields_and_missing_pagination_are_accepted(self):
        self.provider.return_value = (200, {"success": True, "code": "200", "data": {
            "companyList": [{"companyName": "无代码测试企业", "legalPerson": None}],
        }}, "")
        result = self.search().json()
        self.assertEqual(result["status"], "succeeded")
        self.assertIsNone(result["totalRecords"])
        self.search()
        self.assertEqual(BusinessRegistryCompany.objects.count(), 1)

    def test_malformed_row_does_not_partially_save_and_wrong_page_is_rejected(self):
        for response in [success([COMPANY, {"companyName": ""}]), success(page=2), success([COMPANY] * 21)]:
            self.provider.return_value = response
            self.assertEqual(self.search().json()["status"], "failed")
            self.assertFalse(BusinessRegistryCompany.objects.exists())

    def test_earlier_slow_query_does_not_overwrite_newer_company(self):
        earlier = BusinessRegistryQuery.objects.create(request_id=uuid.uuid4(), keyword="测试", page_num=1, page_size=20,
            actor_user_id="admin", effective_user_id="admin")
        current = {**COMPANY, "legalPerson": "最新法人"}
        self.provider.return_value = success([current])
        self.search()
        self.provider.return_value = success()
        complete_query(earlier)
        self.assertEqual(BusinessRegistryCompany.objects.get().legal_person, "最新法人")
        self.assertEqual(BusinessRegistryQuery.objects.get(pk=earlier.pk).companies, [COMPANY])
        history = self.client.get(BASE + f"/companies/{BusinessRegistryCompany.objects.get().pk}/queries").json()
        self.assertEqual(history["total"], 2)
        self.assertEqual(history["items"][-1]["id"], earlier.pk)

    def test_invalid_inputs_do_not_consume_service_calls(self):
        for changes in [{"keyword": " "}, {"keyword": ["测试"]}, {"keyword": "x" * 201},
                        {"pageNum": 0}, {"pageNum": 101}, {"pageSize": 21}, {"pageSize": True},
                        {"pageNum": 1.5}, {"requestId": "invalid"}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.search(**changes).status_code, 400)
        self.assertEqual(self.client.post(BASE + "/search", "[]", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get(BASE + "/companies", {"page": "bad"}).status_code, 400)
        self.provider.assert_not_called()
        self.assertFalse(BusinessRegistryQuery.objects.exists())

    @override_settings(BUSINESS_REGISTRY_APPCODE="")
    def test_missing_configuration_preserves_local_read_access(self):
        self.assertFalse(self.client.get(BASE + "/companies").json()["configured"])
        self.assertEqual(self.search().status_code, 503)
        self.assertEqual(self.client.get(BASE + "/queries").status_code, 200)
        self.assertFalse(BusinessRegistryQuery.objects.exists())
        self.provider.assert_not_called()

    def test_login_permission_and_proxy_enforced_on_every_endpoint(self):
        paths = ["/companies", "/companies/1/queries", "/queries", "/queries/1"]
        self.client.cookies.clear()
        for path in paths:
            self.assertEqual(self.client.get(BASE + path).status_code, 401)
        self.assertEqual(self.search().status_code, 401)
        for actor in [None, self.admin]:
            self.authenticate(self.member, actor)
            for path in paths:
                self.assertEqual(self.client.get(BASE + path).status_code, 403)
            self.assertEqual(self.search().status_code, 403)
        self.provider.assert_not_called()
        self.authenticate(self.admin, self.actor)
        result = self.search().json()
        self.assertEqual((result["actorUserId"], result["effectiveUserId"]), ("actor", "admin"))
        self.assertEqual((result["actorName"], result["effectiveName"]), ("测试操作者", "测试管理员"))

    def test_delegated_administrator_direct_department_and_exclusion_rules(self):
        parent = Department.objects.create(dept_id=10, name="测试总部")
        child = Department.objects.create(dept_id=11, name="测试部门", parent_dept_id=10)
        DepartmentEmployee.objects.create(department=child, employee=self.member)
        PlatformDepartmentState.objects.update_or_create(state_id=1, defaults={"configured": True})
        PlatformEnabledDepartment.objects.create(department=parent)
        PlatformEnabledDepartment.objects.create(department=child)
        self.authenticate(self.member)
        for rule in [{"scopeType": "employee", "targetId": "member"}, {"scopeType": "departmentSub", "targetId": "10"}]:
            OrganizationPermissionState.objects.update_or_create(state_id=1, defaults={"rules": [rule]})
            self.assertEqual(self.client.get(BASE + "/companies").status_code, 200)
            self.assertEqual(self.search().json()["status"], "succeeded")
            OrganizationPermissionState.objects.update_or_create(state_id=1, defaults={"rules": [rule, {"scopeType": "excludedEmployee", "targetId": "member"}]})
            self.assertEqual(self.search().status_code, 403)

    def test_company_column_filters_search_all_saved_rows_and_combine_conditions(self):
        source = BusinessRegistryQuery.objects.create(request_id=uuid.uuid4(), keyword="列筛选测试", page_num=1, page_size=20,
            actor_user_id="admin", effective_user_id="admin")
        stamp = datetime.fromisoformat("2026-10-11T16:00:00+00:00")
        target = BusinessRegistryCompany.objects.create(identity_key="column-target", company_name="列筛选目标企业",
            credit_no="TARGET-CREDIT", company_code="TARGET-REG", legal_person="目标法人", company_status="存续",
            establish_date="20130306", last_queried_at=stamp, last_query=source)
        BusinessRegistryCompany.objects.bulk_create([
            BusinessRegistryCompany(identity_key=f"other-{index}", company_name=f"其他测试企业{index}",
                company_status="注销", last_queried_at=stamp, last_query=source)
            for index in range(25)
        ])
        first = self.client.get(BASE + "/companies").json()
        self.assertEqual(first["total"], 26)
        self.assertNotIn(target.pk, [item["id"] for item in first["items"]])
        filters = {"companyName": "目标", "creditNo": "target-credit", "companyCode": "target-reg", "legalPerson": "目标法人",
                   "companyStatus": "存续", "establishDate": "2013-03-06", "lastQueriedOn": "2026-10-12"}
        result = self.client.get(BASE + "/companies", filters).json()
        self.assertEqual([row["id"] for row in result["items"]], [target.pk])
        self.assertEqual(set(result["filterOptions"]["companyStatuses"]), {"存续", "注销"})
        self.assertEqual(self.client.get(BASE + "/companies", {**filters, "legalPerson": "其他法人"}).json()["total"], 0)
        self.assertEqual(self.client.get(BASE + "/companies", {"lastQueriedOn": "2026-10-11"}).json()["total"], 0)
        target.establish_date = "2013-03-06"
        target.save(update_fields=["establish_date"])
        self.assertEqual(self.client.get(BASE + "/companies", filters).json()["total"], 1)
        self.provider.assert_not_called()

    def test_query_filters_support_zero_results_proxy_actor_and_beijing_day_boundaries(self):
        records = []
        for stamp in ["2026-10-11T15:59:59+00:00", "2026-10-11T16:00:00+00:00", "2026-10-12T15:59:59+00:00", "2026-10-12T16:00:00+00:00"]:
            record = BusinessRegistryQuery.objects.create(request_id=uuid.uuid4(), keyword="查询筛选测试", page_num=2, page_size=20,
                actor_user_id="admin", actor_name="测试管理员", effective_user_id="proxy-id", effective_name="代理人员", status="empty", result_count=0)
            BusinessRegistryQuery.objects.filter(pk=record.pk).update(created_at=datetime.fromisoformat(stamp))
            records.append(record)
        filters = {"keyword": "筛选", "pageNum": "2", "status": "empty", "resultCount": "0", "actor": "代理人员", "createdOn": "2026-10-12"}
        result = self.client.get(BASE + "/queries", filters).json()
        self.assertEqual({item["id"] for item in result["items"]}, {records[1].pk, records[2].pk})
        self.assertEqual(self.client.get(BASE + "/queries", {**filters, "actor": "proxy-id"}).json()["total"], 2)
        self.assertEqual(self.client.get(BASE + "/queries", {**filters, "pageNum": "1"}).json()["total"], 0)
        self.assertEqual(self.client.get(BASE + "/queries", {**filters, "status": "succeeded"}).json()["total"], 0)
        self.provider.assert_not_called()

    def test_invalid_column_filters_return_errors_without_external_calls(self):
        for endpoint, filters in [
            ("companies", {"establishDate": "2026-02-30"}), ("companies", {"lastQueriedOn": "invalid"}),
            ("queries", {"pageNum": "101"}), ("queries", {"resultCount": "-1"}),
            ("queries", {"status": "unknown"}), ("queries", {"createdOn": "2026-10"}),
            ("queries", {"createdOn": "9999-12-31"}), ("companies", {"lastQueriedOn": "0001-01-01"}),
        ]:
            with self.subTest(endpoint=endpoint, filters=filters):
                self.assertEqual(self.client.get(f"{BASE}/{endpoint}", filters).status_code, 400)
        self.provider.assert_not_called()

    def test_cross_origin_post_is_blocked(self):
        self.client.defaults["HTTP_SEC_FETCH_SITE"] = "cross-site"
        self.assertEqual(self.search().status_code, 403)
        self.provider.assert_not_called()

    def test_company_history_links_multiple_searches_and_preserves_complete_snapshots(self):
        other = {**COMPANY, "companyName": "同页其他企业", "creditNo": "OTHER-CREDIT"}
        self.provider.return_value = success([COMPANY, other, COMPANY])
        first = self.search(keyword="原关键词").json()
        changed = {**COMPANY, "companyName": "企业更名", "legalPerson": "新法人"}
        self.provider.return_value = success([changed])
        second = self.search(keyword="不同关键词").json()
        self.provider.return_value = success([other])
        unrelated = self.search(keyword="只命中其他企业").json()
        company = BusinessRegistryCompany.objects.get(credit_no=COMPANY["creditNo"])
        endpoint = BASE + f"/companies/{company.pk}/queries"
        history = self.client.get(endpoint).json()
        self.assertEqual([item["id"] for item in history["items"]], [second["id"], first["id"]])
        self.assertNotIn(unrelated["id"], [item["id"] for item in history["items"]])
        self.assertEqual(history["total"], 2)
        self.assertEqual(history["company"]["companyName"], "企业更名")
        self.assertNotIn("companies", history["items"][0])
        self.assertEqual(self.client.get(BASE + f'/queries/{first["id"]}').json()["companies"], [COMPANY, other, COMPANY])
        self.assertEqual(self.client.get(BASE + f'/queries/{second["id"]}').json()["companies"], [changed])
        self.assertEqual(self.client.get(BASE + "/companies", {"creditNo": COMPANY["creditNo"]}).json()["items"][0]["queryCount"], 2)
        self.assertEqual(BusinessRegistryQueryCompany.objects.filter(company=company).count(), 2)
        self.assertEqual(BusinessRegistryCompany.objects.count(), 2)
        self.assertEqual(self.client.get(endpoint, {"page": 2}).json()["items"], [])
        self.assertEqual(self.client.get(endpoint, {"page": "invalid"}).status_code, 400)
        self.assertEqual(self.client.get(BASE + "/companies/999999/queries").status_code, 404)
        self.assertEqual(self.provider.call_count, 3, "History only reads saved records")

    def test_company_history_paginates_without_duplicates_or_external_calls(self):
        first = self.search().json()
        company = BusinessRegistryCompany.objects.get()
        records = [BusinessRegistryQuery.objects.create(request_id=uuid.uuid4(), keyword=f"历史 {index}",
            page_num=1, page_size=20, status="succeeded", actor_user_id="admin", effective_user_id="admin")
            for index in range(21)]
        BusinessRegistryQueryCompany.objects.bulk_create([
            BusinessRegistryQueryCompany(company=company, query=record) for record in records
        ])
        endpoint = BASE + f"/companies/{company.pk}/queries"
        page1 = self.client.get(endpoint).json()
        page2 = self.client.get(endpoint, {"page": 2}).json()
        self.assertEqual(page1["total"], 22)
        self.assertEqual(len(page1["items"]), 20)
        self.assertEqual([row["id"] for row in page1["items"] + page2["items"]], [r.pk for r in reversed(records)] + [first["id"]])
        self.provider.assert_called_once()


class BusinessRegistryHistoryMigrationTests(TransactionTestCase):
    def test_backfill_links_old_snapshots_and_last_query_without_changing_saved_data(self):
        before = [("identity_api", "0018_business_registry")]
        after = [("identity_api", "0019_business_registry_company_history")]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            old_apps = executor.loader.project_state(before).apps
            Company = old_apps.get_model("identity_api", "BusinessRegistryCompany")
            Query = old_apps.get_model("identity_api", "BusinessRegistryQuery")
            masked = {**COMPANY, "creditNo": "****", "companyCode": "****", "companyName": "脱敏企业"}
            code_only = {**COMPANY, "creditNo": "", "companyCode": "CODE-ONLY"}
            renamed = {**COMPANY, "companyName": "企业更名", "creditNo": COMPANY["creditNo"].lower()}
            snapshots = [[COMPANY, masked, code_only, COMPANY], [renamed, masked, code_only]]
            records = [Query.objects.create(request_id=uuid.uuid4(), keyword=f"旧查询 {index}", page_num=1,
                page_size=20, status="succeeded", companies=snapshot, response_payload={"saved": snapshot})
                for index, snapshot in enumerate(snapshots)]
            latest = records[-1]
            for row in [renamed, masked, code_only]:
                Company.objects.create(identity_key=identity_key(row), company_name=row["companyName"],
                    last_query=latest, last_queried_at=latest.created_at)
            # Preserve the known latest relationship even when an old identity cannot be matched.
            Company.objects.create(identity_key="legacy-identity", company_name="已有关系",
                last_query=latest, last_queried_at=latest.created_at)
            companies_before = list(Company.objects.order_by("pk").values())
            queries_before = list(Query.objects.order_by("pk").values())
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            new_apps = executor.loader.project_state(after).apps
            Link = new_apps.get_model("identity_api", "BusinessRegistryQueryCompany")
            self.assertEqual(Link.objects.count(), 7)
            self.assertEqual(Link.objects.filter(query_id=records[0].pk).count(), 3)
            self.assertEqual(Link.objects.filter(query_id=latest.pk).count(), 4)
            migration = import_module("identity_api.migrations.0019_business_registry_company_history")
            with connection.schema_editor() as editor:
                migration.backfill_company_queries(new_apps, editor)
            self.assertEqual(Link.objects.count(), 7, "Re-running the backfill must not duplicate links")
            self.assertEqual(list(Company.objects.order_by("pk").values()), companies_before)
            self.assertEqual(list(Query.objects.order_by("pk").values()), queries_before)
        finally:
            MigrationExecutor(connection).migrate(after)


class BusinessRegistryClientTests(SimpleTestCase):
    @patch("identity_api.org.business_registry_client.requests.post")
    def test_client_uses_form_auth_timeout_no_redirect_and_redacts_credentials(self, post):
        response = MagicMock()
        response.status_code = 200
        response.headers = {"X-Ca-Request-Id": "gateway-id"}
        response.iter_content.return_value = [json.dumps({"msg": "test-credential"}).encode()]
        post.return_value.__enter__.return_value = response
        status, payload, request_id = query_company_service("test-credential", "迈杰", 2, 20)
        self.assertEqual((status, payload, request_id), (200, {"msg": "[redacted]"}, "gateway-id"))
        post.assert_called_once_with(QUERY_URL, headers={"Authorization": "APPCODE test-credential", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                                    data={"keyword": "迈杰", "pageNum": "2", "pageSize": "20"}, timeout=(5, 20), allow_redirects=False, stream=True)

    @patch("identity_api.org.business_registry_client.requests.post")
    def test_non_json_gateway_error_preserves_http_status(self, post):
        response = MagicMock(status_code=403, headers={})
        response.iter_content.return_value = [b"<html>Forbidden</html>"]
        post.return_value.__enter__.return_value = response
        self.assertEqual(query_company_service("test-credential", "test", 1, 20), (403, {}, ""))
