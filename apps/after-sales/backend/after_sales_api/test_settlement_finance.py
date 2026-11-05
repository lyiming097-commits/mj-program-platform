from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch
from unittest import skipUnless
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.apps import apps
from django.db import close_old_connections, connection, connections
from django.test import RequestFactory, TestCase, TransactionTestCase

from . import views
from .models import ProjectAssignment, ProjectNode, ServiceProject, ServiceProvider, Settlement, SettlementEvent
from .settlement_finance import settlement_companies, settlement_projects
from .test_messages_settlements import ApiRequestMixin


class SettlementFinanceTests(ApiRequestMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        # The demo data migration contains legacy finance rows; isolate this ledger fixture.
        SettlementEvent.objects.all().delete()
        Settlement.objects.all().delete()
        ProjectNode.objects.update(actual_fee=None)
        self.project = ServiceProject.objects.create(code="FIN-1", service_type="midsales", name="财务项目", customer="客户", owner_user_id="owner-1")
        self.node = ProjectNode.objects.create(project=self.project, node_key="construction-work", name="工程施工", sequence=1,
            status="completed", actual_fee=1000, estimated_fee=800, business_data={"externalQuote": "1500"})

    def create(self, **overrides):
        response = views.settlements_collection(self.request("post", "/api/after-sales/settlements", {
            "sourceNodeId": self.node.id, "bearer": "customer", **overrides,
        }))
        self.assertEqual(response.status_code, 201, self.data(response))
        return self.data(response)["item"]

    def update(self, item, **values):
        return views.settlement_item(self.request("patch", f"/api/after-sales/settlements/{item['id']}", {
            "expectedRevision": item["revision"], **values,
        }), item["id"])

    def test_partial_receipts_and_post_settlement_invoices_keep_signed_ledger(self):
        item = self.create(receivedAmount=500, status="pending")
        self.assertEqual(item["receivedAmount"], "500.00")
        self.assertEqual(item["status"], "pending")
        response = self.update(item, receivedAmount=1500, status="settled")
        self.assertEqual(response.status_code, 200, self.data(response))
        item = self.data(response)["item"]
        for amount, invoice_number in ((600, "票-A"), (1500, "票-B")):
            response = self.update(item, invoicedAmount=amount, invoiceNumber=invoice_number, invoiceType="13%增值税")
            self.assertEqual(response.status_code, 200, self.data(response))
            item = self.data(response)["item"]
        self.assertEqual(item["status"], "settled")
        self.assertEqual(item["remainingInvoice"], "0.00")
        record = Settlement.objects.get(pk=item["id"])
        self.assertEqual(sum(event.receipt_delta for event in record.events.all()), Decimal("1500"))
        self.assertEqual(sum(event.invoice_delta for event in record.events.all()), Decimal("1500"))
        self.assertEqual(record.events.get(revision=3).after["invoice_number"], "票-A")
        self.assertEqual(record.events.get(revision=4).after["invoice_number"], "票-B")
        self.assertEqual(record.events.get(revision=4).operator_name, "系统管理员")

    def test_stale_and_missing_revisions_cannot_overwrite_financial_data(self):
        item = self.create()
        response = self.update(item, receivedAmount=100)
        self.assertEqual(response.status_code, 200)
        stale = self.update(item, receivedAmount=200)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.data(stale)["code"], "SETTLEMENT_REVISION_CONFLICT")
        missing = views.settlement_item(self.request("patch", f"/api/after-sales/settlements/{item['id']}", {"receivedAmount": 300}), item["id"])
        self.assertEqual(missing.status_code, 409)
        self.assertEqual(self.data(missing)["code"], "SETTLEMENT_REVISION_REQUIRED")
        self.assertEqual(Settlement.objects.get(pk=item["id"]).received_amount, Decimal("100"))
        self.assertEqual(SettlementEvent.objects.count(), 2)

    def test_corrections_require_reason_and_reopen_when_no_longer_paid(self):
        item = self.create(receivedAmount=1500, status="settled")
        denied = self.update(item, receivedAmount=1200)
        self.assertEqual(self.data(denied)["code"], "SETTLEMENT_CORRECTION_REASON_REQUIRED")
        denied = self.update(item, receivedAmount=1200, correctionReason="误录 300")
        self.assertEqual(self.data(denied)["code"], "SETTLEMENT_REOPEN_REQUIRED")
        corrected = self.update(item, receivedAmount=1200, status="pending", correctionReason="误录 300")
        self.assertEqual(corrected.status_code, 200, self.data(corrected))
        item = self.data(corrected)["item"]
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["events"][0]["receiptDelta"], "-300.00")
        self.assertEqual(item["events"][0]["reason"], "误录 300")

    def test_cancel_preserves_history_and_requires_balance_reversal(self):
        item = self.create(receivedAmount=500, invoicedAmount=100)
        denied = self.update(item, status="cancelled", correctionReason="录错来源")
        self.assertEqual(self.data(denied)["code"], "SETTLEMENT_CANCEL_HAS_BALANCE")
        response = self.update(item, status="cancelled", receivedAmount=0, invoicedAmount=0, correctionReason="已冲回，录错来源")
        self.assertEqual(response.status_code, 200, self.data(response))
        cancelled = self.data(response)["item"]
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(len(cancelled["events"]), 2)
        replacement = self.create()
        self.assertNotEqual(replacement["id"], item["id"])
        locked = self.update(cancelled, remark="覆盖历史")
        self.assertEqual(self.data(locked)["code"], "SETTLEMENT_LOCKED")

    def test_no_op_does_not_add_events_or_increase_revision(self):
        item = self.create(receivedAmount=500)
        response = self.update(item, receivedAmount=500)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.data(response)["item"]["revision"], 1)
        self.assertEqual(SettlementEvent.objects.count(), 1)

    def test_invoice_reduction_requires_reason_even_before_settlement(self):
        item = self.create(invoicedAmount=500)
        denied = self.update(item, invoicedAmount=100)
        self.assertEqual(self.data(denied)["code"], "SETTLEMENT_CORRECTION_REASON_REQUIRED")
        response = self.update(item, invoicedAmount=100, correctionReason="红冲发票")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.data(response)["item"]["events"][0]["invoiceDelta"], "-400.00")

    def test_invoice_registration_preserves_historical_customer_subject_fields(self):
        item = self.create(receivedAmount=1500, status="settled")
        Settlement.objects.filter(pk=item["id"]).update(subject_type="", subject_name="历史客户抬头")
        response = self.update(item, invoicedAmount=100, invoiceNumber="HISTORY-1")
        self.assertEqual(response.status_code, 200, self.data(response))
        updated = self.data(response)["item"]
        self.assertEqual(updated["subjectName"], "历史客户抬头")
        self.assertEqual(updated["subjectType"], "")
        self.assertEqual(updated["status"], "settled")

    def test_presales_never_enters_settlement_even_with_legacy_node_fees(self):
        self.project.service_type = "presales"
        self.project.current_node_key = self.node.node_key
        self.project.save()
        other = ProjectNode.objects.create(project=self.project, node_key="budget-match", name="预算匹配", sequence=2,
            status="active", actual_fee=200, business_data={"externalQuote": "300"})
        response = views.settlement_sources(self.request("get", "/api/after-sales/settlement-sources", query={"state": "all"}))
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertEqual(self.data(response)["items"], [])
        from .serializers import serialize_project
        from .services import unsettled_settlement_nodes
        detail = serialize_project(self.project, detail=True)
        self.assertFalse(detail["settlementRequired"])
        self.assertEqual(detail["settlementItems"], [])
        self.assertEqual(unsettled_settlement_nodes(self.project, list(self.project.nodes.all())), [])
        for node in (self.node, other):
            response = views.settlements_collection(self.request("post", "/api/after-sales/settlements", {
                "sourceNodeId": node.id, "bearer": "customer",
            }))
            self.assertEqual(response.status_code, 409, self.data(response))
            self.assertEqual(self.data(response)["code"], "SETTLEMENT_SOURCE_NOT_CHARGEABLE")
        # Preserve historical finance data without including it in the service ledger.
        legacy = Settlement.objects.create(code="OLD-PRESALES", project=self.project, service_type="presales", customer="客户")
        response = views.settlement_sources(self.request("get", "/", query={"state": "all"}))
        self.assertEqual(self.data(response)["total"], 0)
        response = views.settlements_collection(self.request("get", "/"))
        self.assertEqual(self.data(response)["items"], [])
        self.assertTrue(Settlement.objects.filter(pk=legacy.pk).exists())

    def test_pagination_and_search_cover_more_than_one_hundred_sources(self):
        projects = [ServiceProject(code=f"FIN-P-{i}", service_type="midsales", name=f"分页项目{i}", customer="客户") for i in range(105)]
        ServiceProject.objects.bulk_create(projects)
        ProjectNode.objects.bulk_create([ProjectNode(project=p, node_key="construction-work", name="工程施工", sequence=1,
            status="completed", actual_fee=100, business_data={"externalQuote": "200"}) for p in projects])
        response = views.settlement_sources(self.request("get", "/api/after-sales/settlement-sources", query={"state": "all", "pageSize": 20, "page": 6}))
        self.assertEqual(response.status_code, 200, self.data(response))
        data = self.data(response)
        self.assertEqual(data["total"], 106)
        self.assertEqual(data["totalPages"], 6)
        self.assertEqual(len(data["items"]), 6)
        found = views.settlement_sources(self.request("get", "/api/after-sales/settlement-sources", query={"state": "all", "search": "财务项目"}))
        self.assertEqual(self.data(found)["total"], 1)
        self.assertEqual(self.data(found)["items"][0]["projectName"], "财务项目")
        found = views.settlement_sources(self.request("get", "/api/after-sales/settlement-sources", query={
            "state": "all", "projectSearch": "财务项目", "pageSize": 20, "page": 6,
        }))
        self.assertEqual(self.data(found)["total"], 1)
        self.assertEqual(self.data(found)["page"], 1)

    def test_column_filters_are_independent_and_cover_legacy_rows_before_pagination(self):
        self.project.name = "独立项目 Alpha"
        self.project.customer = "学校客户 Beta"
        self.project.owner_name = "陈经理"
        self.project.save()
        legacy = Settlement.objects.create(code="FILTER-LEGACY", project=self.project, service_type="midsales",
            customer="历史客户 Gamma", bearer="customer", service_content="Alpha Beta 陈经理", status="pending")

        def query(**filters):
            response = views.settlement_sources(self.request("get", "/api/after-sales/settlement-sources", query={
                "state": "all", **filters,
            }))
            self.assertEqual(response.status_code, 200, self.data(response))
            return self.data(response)

        for filters, expected_ids in (
            ({"projectSearch": "alpha"}, {self.node.id, f"legacy-{legacy.id}"}),
            ({"customerSearch": "Beta"}, {self.node.id}),
            ({"customerSearch": "Gamma"}, {f"legacy-{legacy.id}"}),
            ({"ownerSearch": "陈"}, {self.node.id, f"legacy-{legacy.id}"}),
            ({"projectSearch": "Beta"}, set()),
            ({"customerSearch": "Alpha"}, set()),
            ({"ownerSearch": "Alpha"}, set()),
            ({"projectSearch": "Alpha", "customerSearch": "Beta", "ownerSearch": "陈"}, {self.node.id}),
            ({"projectSearch": "Alpha", "customerSearch": "Beta", "ownerSearch": "其他人"}, set()),
            ({"projectSearch": "  Alpha  ", "customerSearch": " Gamma ", "ownerSearch": " 陈 "}, {f"legacy-{legacy.id}"}),
        ):
            with self.subTest(filters=filters):
                data = query(**filters)
                self.assertEqual(data["total"], len(expected_ids))
                self.assertEqual({item["id"] for item in data["items"]}, expected_ids)

        data = query(projectSearch="Alpha", ownerSearch="陈", pageSize=1, page=2)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["totalPages"], 2)
        self.assertEqual(data["items"][0]["id"], f"legacy-{legacy.id}")
        self.assertEqual(data["items"][0]["customer"], "历史客户 Gamma")

    def test_company_cost_and_customer_quote_are_distinct_snapshots(self):
        item = self.create(bearer="company")
        self.assertEqual(item["orderAmount"], "1000.00")
        self.assertEqual(item["externalQuote"], "1500.00")
        self.assertEqual(item["remainingReceivable"], "0")
        self.node.actual_fee = 20
        self.node.business_data = {"externalQuote": "50"}
        self.node.save()
        response = views.settlement_sources(self.request("get", "/api/after-sales/settlement-sources", query={"state": "all"}))
        source = self.data(response)["items"][0]
        self.assertEqual(source["actualFee"], "1000.00")
        self.assertEqual(source["externalQuote"], "1500.00")

    def test_related_projects_use_ids_and_include_unsettled_projects_without_cost(self):
        unrelated = ServiceProject.objects.create(code="UNRELATED", service_type="midsales", name="同名人员项目", customer="客户", owner_user_id="owner-10")
        related = ServiceProject.objects.create(code="RELATED", service_type="midsales", name="执行人项目", customer="客户")
        ProjectNode.objects.create(project=related, node_key="early-plan", name="前期方案", sequence=1, business_data={"managementAssignment": {"userId": "owner-1", "name": "同名"}})
        response = settlement_projects(self.request("get", "/api/after-sales/settlement-projects", query={"userId": "owner-1"}))
        self.assertEqual({item["id"] for item in self.data(response)["items"]}, {self.project.id, related.id})
        self.assertNotIn(unrelated.id, {item["id"] for item in self.data(response)["items"]})

    @patch("after_sales_api.views._active_employee_directory", return_value=([{"userId": "owner-1", "name": "真实姓名"}], "1"))
    def test_subject_uses_authority_name_and_rejects_unrelated_project(self, _employees):
        item = self.create(bearer="company", subjectType="person", subjectId="owner-1", subjectName="伪造姓名", relatedProjectId=self.project.id)
        self.assertEqual(item["subjectName"], "真实姓名")
        other = ServiceProject.objects.create(code="OTHER", service_type="midsales", name="无关项目", customer="客户")
        response = self.update(item, relatedProjectId=other.id)
        self.assertEqual(self.data(response)["code"], "SETTLEMENT_PERSON_PROJECT_MISMATCH")

    def test_presales_cannot_be_selected_as_a_related_settlement_project(self):
        presales = ServiceProject.objects.create(code="NO-FIN", service_type="presales", name="售前项目", customer="客户", owner_user_id="owner-1")
        response = settlement_projects(self.request("get", "/", query={"userId": "owner-1"}))
        self.assertNotIn(presales.id, {row["id"] for row in self.data(response)["items"]})
        response = views.settlements_collection(self.request("post", "/", {
            "sourceNodeId": self.node.id, "bearer": "company", "relatedProjectId": presales.id,
        }))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.data(response)["code"], "SETTLEMENT_PRESALES_NOT_SUPPORTED")

    @patch("after_sales_api.settlement_finance.get_auth_company_entities", return_value=[{"id": 17, "companyName": "平台主体", "pinyin": "pingtai", "pinyinInitials": "pt"}])
    def test_company_directory_replaces_hardcoded_options(self, _directory):
        response = settlement_companies(self.request("get", "/api/after-sales/settlement-companies"))
        self.assertEqual(self.data(response)["items"][0]["id"], 17)
        item = self.create(bearer="company", subjectType="company", subjectId="17", subjectName="不可信名称")
        self.assertEqual(item["subjectName"], "平台主体")
        denied = self.update(item, subjectId="999", subjectName="未知公司")
        self.assertEqual(self.data(denied)["code"], "SETTLEMENT_SUBJECT_NOT_FOUND")

    def test_cancelled_assignments_cannot_supply_active_settlement_readiness(self):
        self.project.service_type = "midsales"; self.project.save()
        self.node.node_key = "device-install"; self.node.status = "active"; self.node.save()
        provider = ServiceProvider.objects.create(auth_user_id="field", name="现场人员")
        cancelled = ProjectAssignment.objects.create(project=self.project, node=self.node, provider=provider, status="cancelled")
        replacement_provider = ServiceProvider.objects.create(auth_user_id="field-new", name="新现场人员")
        current = ProjectAssignment.objects.create(project=self.project, node=self.node, provider=replacement_provider, status="in_progress")
        self.node.business_data = {"fieldSubmissions": {str(cancelled.id): {"submitted": True}}}; self.node.save()
        response = views.settlement_sources(self.request("get", "/api/after-sales/settlement-sources"))
        self.assertEqual(self.data(response)["total"], 0)
        self.node.business_data["fieldSubmissions"][str(current.id)] = {"submitted": True}; self.node.save()
        response = views.settlement_sources(self.request("get", "/api/after-sales/settlement-sources"))
        self.assertEqual(self.data(response)["total"], 1)

    def test_historical_backfill_is_an_opening_balance_not_a_new_payment(self):
        item = Settlement.objects.create(code="LEGACY", project=self.project, source_node=self.node, bearer="customer",
            service_type="presales", customer="客户", order_amount=1500, received_amount=500, invoiced_amount=100)
        original_time = item.updated_at
        migration = import_module("after_sales_api.migrations.0027_settlement_history_opening")
        migration.opening_balances(apps, SimpleNamespace(connection=connection))
        event = item.events.get()
        self.assertEqual(event.kind, "opening")
        self.assertEqual(event.created_at, original_time)
        self.assertIn("非本次新增", event.reason)
        item.refresh_from_db()
        self.assertEqual(item.external_quote, Decimal("1500"))

    def test_finance_endpoints_deny_field_users(self):
        ServiceProvider.objects.create(auth_user_id="ordinary", name="小程序人员")
        for endpoint in (views.settlement_sources, settlement_projects, settlement_companies):
            response = endpoint(self.request("get", "/api/after-sales/settlement-sources", admin=False, user_id="ordinary"))
            self.assertIn(response.status_code, (403, 503))

    @patch("after_sales_api.crm_source.crm_visible_ids", return_value=["crm-visible"])
    def test_source_and_related_project_lists_keep_crm_scope(self, _scope):
        hidden = ServiceProject.objects.create(code="CRM-HIDDEN", service_type="presales", name="不可见项目", customer="隐私客户", source_crm_id="crm-hidden")
        ProjectNode.objects.create(project=hidden, node_key="early-plan", name="前期方案", sequence=1, status="active", actual_fee=100)
        Settlement.objects.create(code="RELATED-HIDDEN", project=self.project, source_node=self.node, related_project=hidden,
            service_type="presales", customer="客户", bearer="company")
        response = views.settlement_sources(self.request("get", "/api/after-sales/settlement-sources", query={"state": "all"}))
        self.assertEqual(self.data(response)["total"], 0)
        response = settlement_projects(self.request("get", "/api/after-sales/settlement-projects"))
        self.assertNotIn(hidden.id, {item["id"] for item in self.data(response)["items"]})

    def test_financial_nan_infinity_and_overflow_are_rejected(self):
        for amount in ("NaN", "Infinity", "10000000000", "-1"):
            with self.subTest(amount=amount):
                response = views.settlements_collection(self.request("post", "/api/after-sales/settlements", {
                    "sourceNodeId": self.node.id, "bearer": "customer", "receivedAmount": amount,
                }))
                self.assertEqual(response.status_code, 400, self.data(response))
                self.assertFalse(Settlement.objects.filter(source_node=self.node).exists())


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class SettlementConcurrentWriteTests(ApiRequestMixin, TransactionTestCase):
    def test_two_editors_with_same_revision_cannot_both_commit(self):
        self.factory = RequestFactory()
        project = ServiceProject.objects.create(code="CONCURRENT-FIN", service_type="presales", name="并发财务", customer="客户")
        settlement = Settlement.objects.create(code="CONCURRENT-SET", project=project, service_type="presales", customer="客户",
            bearer="customer", order_amount=1500, invoice_due_amount=1500)
        barrier = Barrier(2)

        def write(amount):
            close_old_connections()
            try:
                request = self.request("patch", f"/api/after-sales/settlements/{settlement.pk}", {"expectedRevision": 1, "receivedAmount": amount})
                barrier.wait(timeout=10)
                return views.settlement_item(request, settlement.pk).status_code
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, [100, 200]))
        self.assertEqual(sorted(results), [200, 409])
        settlement.refresh_from_db()
        self.assertEqual(settlement.revision, 2)
        self.assertIn(settlement.received_amount, [Decimal("100"), Decimal("200")])
        self.assertEqual(settlement.events.count(), 1)
