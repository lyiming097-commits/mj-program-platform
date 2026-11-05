from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

from . import crm_source, services, views
from .models import ProjectNode
from .serializers import serialize_project
from .test_crm_source import opportunity
from .tests import CleanDomainMixin, RequestMixin


class PresalesProjectLeadTests(RequestMixin, CleanDomainMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.clear_domain()
        cache.clear()
        self.addCleanup(cache.clear)
        self.project = services.create_project(self.request("post", "/"), {
            "code": "project-leads", "name": "负责人测试", "customer": "学校",
            "service_type": "presales", "status": "in_progress",
            "owner_user_id": "sales-user", "owner_name": "销售甲",
        })
        self.design = {"userId": "design-user", "name": "设计甲"}
        self.solution = {"userId": "solution-user", "name": "方案乙"}

    def save(self, leads, *, node_key="early-approval", stamp=None, admin=True):
        node = self.project.nodes.get(node_key=node_key)
        payload = {"expectedUpdatedAt": stamp or node.updated_at.isoformat(),
                   "businessData": {"projectLeads": leads}}
        return views.project_node_autosave(self.request("patch", "/", payload, admin=admin),
                                          self.project.pk, node_key)

    def listing(self, **query):
        request = self.request("get", "/", query={"type": "presales", **query})
        crm_source._remember_scope(request, [], synced=True)
        with patch.object(views, "sync_crm_presales"), CaptureQueriesContext(connection) as queries:
            response = views.projects_collection(request)
        self.assertEqual(response.status_code, 200, self.data(response))
        # Fuzzy person searches use one bounded scan, matching the existing
        # customer/sales-owner filters; the page itself stays at five queries.
        self.assertLessEqual(len(queries), 5 + bool(query.get("designOwnerSearch")) + bool(query.get("solutionOwnerSearch")))
        return self.data(response)

    def test_roles_save_independently_and_list_with_sales_owner_without_n_plus_one(self):
        self.assertEqual(self.save({"design": self.design}).status_code, 200)
        response = self.save({"solution": self.solution})
        self.assertEqual(response.status_code, 200, self.data(response))
        expected = {"design": self.design, "solution": self.solution}
        self.assertEqual(self.data(response)["item"]["projectLeads"], expected)
        # An ordinary node draft does not erase these roles or assign executors.
        services.save_project_node_draft(self.request("post", "/"), self.project.pk,
                                        node_key="early-approval", node_values={"business_data": {"note": "立项备注"}})
        self.project.refresh_from_db()
        self.assertEqual(self.project.owner_user_id, "sales-user")
        self.assertFalse(self.project.nodes.exclude(business_data__managementAssignment__isnull=True).exists())
        for index in range(22):
            services.create_project(self.request("post", "/"), {
                "code": f"other-{index}", "name": f"其它项目 {index}", "service_type": "presales",
            })
        payload = self.listing(nameSearch="负责人测试", pageSize=20)
        self.assertEqual(payload["total"], 1)
        item = payload["items"][0]
        self.assertEqual(item["projectLeads"], expected)
        self.assertEqual(item["ownerName"], "销售甲")
        self.assertNotIn("nodes", item)
        self.assertEqual(len(self.listing(pageSize=20)["items"]), 20)
        self.assertEqual(self.listing(designOwnerSearch="设计甲")["total"], 1)
        self.assertEqual(self.listing(solutionOwnerSearch="方案乙")["total"], 1)
        self.assertEqual(self.listing(designOwnerSearch="方案乙")["total"], 0)

    def test_concurrent_save_cannot_overwrite_another_role(self):
        stamp = self.project.nodes.get(node_key="early-approval").updated_at.isoformat()
        self.save({"design": self.design}, stamp=stamp)
        response = self.save({"solution": self.solution}, stamp=stamp)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.data(response)["code"], "PROJECT_NODE_CONFLICT")
        self.assertEqual(self.project.nodes.get(node_key="early-approval").business_data["projectLeads"],
                         {"design": self.design})

    def test_presales_drafts_and_progress_cannot_replace_source_fees_with_node_fees(self):
        node = self.project.nodes.get(node_key="early-approval")
        node.estimated_fee, node.actual_fee = 5, 10
        node.business_data = {"externalQuote": "15"}
        node.save()
        for target in self.project.nodes.filter(node_key__in=["early-plan", "budget-match", "project-filing"]):
            target.business_data = {"managementAssignment": {"userId": "design-user", "name": "设计甲"}}
            target.save()
        for action in ("draft", "advance"):
            node.refresh_from_db()
            payload = {"expectedUpdatedAt": node.updated_at.isoformat(), "estimatedFee": "999",
                       "actualFee": "888", "businessData": {"externalQuote": "777", "external_quote": "666", "deliveryNote": "保留节点说明"}}
            if action == "draft":
                response = views.project_node_autosave(self.request("patch", "/", payload), self.project.pk, node.node_key)
            else:
                payload.update(nodeKey=node.node_key, outcome="approved")
                response = views.project_advance(self.request("post", "/", payload), self.project.pk)
            self.assertEqual(response.status_code, 200, self.data(response))
            node.refresh_from_db()
            self.assertEqual(node.estimated_fee, 5)
            self.assertEqual(node.actual_fee, 10)
            self.assertEqual(node.business_data["externalQuote"], "15")
            self.assertNotIn("external_quote", node.business_data)
            self.assertEqual(node.business_data["deliveryNote"], "保留节点说明")

    def test_single_lead_list_search_and_clearing_preserve_the_other_role(self):
        self.save({"solution": self.solution})
        response = self.save({"design": {"members": [self.design, self.design],
                                          "userIds": ["unselected-user"]}})
        self.assertEqual(response.status_code, 200, self.data(response))
        leads = self.data(response)["item"]["projectLeads"]
        self.assertEqual(leads["design"]["members"], [self.design])
        self.assertEqual(leads["design"]["userIds"], ["design-user"])
        self.assertEqual(leads["design"]["name"], "设计甲")
        self.assertEqual(leads["solution"], self.solution)
        for query in ("设计甲", "design-user"):
            self.assertEqual(self.listing(designOwnerSearch=query)["total"], 1)
        self.assertEqual(self.listing(designOwnerSearch="unselected-user")["total"], 0)
        response = self.save({"design": {"members": []}})
        leads = self.data(response)["item"]["projectLeads"]
        self.assertEqual(leads["design"]["members"], [])
        self.assertEqual(leads["design"]["userId"], "")
        self.assertEqual(leads["solution"], self.solution)

    def test_each_role_rejects_multiple_people_without_replacing_saved_roles(self):
        self.save({"design": self.design, "solution": self.solution})
        for role in ("design", "solution"):
            with self.subTest(role=role):
                response = self.save({role: {"members": [self.design, self.solution]}})
                self.assertEqual(response.status_code, 400, self.data(response))
                self.assertEqual(self.data(response)["code"], "INVALID_PROJECT_LEADS")
                self.assertEqual(self.project.nodes.get(node_key="early-approval").business_data["projectLeads"],
                                 {"design": self.design, "solution": self.solution})

    def test_historical_multiple_leads_remain_readable_and_can_be_replaced_with_one(self):
        legacy = {"members": [self.design, self.solution],
                  "userIds": ["design-user", "solution-user"],
                  "userId": "design-user", "name": "设计甲、方案乙"}
        self.project.nodes.filter(node_key="early-approval").update(business_data={"projectLeads": {"design": legacy}})
        self.assertEqual(self.listing(designOwnerSearch="方案乙")["items"][0]["projectLeads"]["design"], legacy)
        response = self.save({"solution": self.solution})
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertEqual(self.data(response)["item"]["projectLeads"]["design"], legacy)
        response = self.save({"design": {"members": [self.design]}})
        self.assertEqual(response.status_code, 200, self.data(response))
        leads = self.data(response)["item"]["projectLeads"]
        self.assertEqual(leads["design"]["members"], [self.design])
        self.assertEqual(leads["design"]["userIds"], ["design-user"])
        self.assertEqual(leads["solution"], self.solution)

    def test_malformed_multi_person_selection_cannot_replace_saved_role(self):
        self.save({"design": self.design})
        for members in (None, "x", [None], [{"userId": "a"}], [{"userId": 2, "name": "乙"}]):
            with self.subTest(members=members):
                self.assertEqual(self.save({"design": {"members": members}}).status_code, 400)
        self.assertEqual(self.project.nodes.get(node_key="early-approval").business_data["projectLeads"]["design"], self.design)

    def test_invalid_and_wrong_node_updates_leave_saved_roles_intact(self):
        self.save({"design": self.design})
        for invalid in (None, [], {"unknown": self.design}, {"design": "x"},
                        {"design": {"userId": "x"}}, {"design": {"userId": 3, "name": "甲"}}):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.save(invalid).status_code, 400)
        self.assertEqual(self.save({"solution": self.solution}, node_key="early-plan").status_code, 400)
        self.assertEqual(self.project.nodes.get(node_key="early-approval").business_data["projectLeads"],
                         {"design": self.design})

    def test_completed_approval_and_unauthorized_user_cannot_change_roles(self):
        self.save({"design": self.design})
        response = self.save({"solution": self.solution}, admin=False)
        self.assertEqual(response.status_code, 403)
        self.project.nodes.filter(node_key="early-approval").update(status=ProjectNode.STATUS_COMPLETED)
        response = self.save({"solution": self.solution})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.data(response)["code"], "PROJECT_NODE_AUTOSAVE_LOCKED")

    def test_crm_refresh_changes_sales_owner_but_keeps_service_project_roles(self):
        request = self.request("post", "/")
        project = crm_source._sync_row(request, opportunity("crm-project-leads"))
        with patch.object(crm_source, "_request_payload", return_value={"item": opportunity("crm-project-leads")}):
            services.save_project_node_draft(request, project.pk, node_key="early-approval", node_values={
                "business_data": {"projectLeads": {"design": self.design, "solution": self.solution}},
            })
        crm_source._sync_row(request, opportunity("crm-project-leads", owner="新销售", ownerUserId="new-sales"))
        project.refresh_from_db()
        item = serialize_project(project, detail=True)
        self.assertEqual(item["ownerName"], "新销售")
        self.assertEqual(item["projectLeads"], {"design": self.design, "solution": self.solution})
