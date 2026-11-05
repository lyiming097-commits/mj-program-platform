from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from . import services, views
from .models import ProjectNode, ServiceProject
from .tests import CleanDomainMixin, RequestMixin


class ParallelNodeSummaryTests(RequestMixin, CleanDomainMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.clear_domain()
        cache.clear()
        self.addCleanup(cache.clear)
        self.enterContext(patch("after_sales_api.crm_source._request_payload", return_value={"items": []}))
        self.project = services.create_project(self.request("post", "/"), {
            "code": "parallel-summary", "name": "并行节点项目", "customer": "测试学校",
            "service_type": "presales",
        })

    def set_active(self, keys):
        self.project.nodes.update(status=ProjectNode.STATUS_PENDING)
        self.project.nodes.filter(node_key__in=keys).update(status=ProjectNode.STATUS_ACTIVE)
        self.project.current_node_key = keys[0]
        self.project.save(update_fields=["current_node_key"])

    def list_payload(self, **filters):
        response = views.projects_collection(self.request("get", "/", query={"type": "presales", **filters}))
        self.assertEqual(response.status_code, 200)
        return self.data(response)

    def test_list_detail_and_overview_report_both_active_branches(self):
        self.set_active(["early-plan", "budget-match"])
        payload = self.list_payload()
        expected = [{"nodeKey": "early-plan", "name": "前期方案"}, {"nodeKey": "budget-match", "name": "预算匹配"}]
        self.assertEqual(payload["items"][0]["activeNodes"], expected)
        self.assertNotIn("nodes", payload["items"][0])
        detail = self.data(views.project_item(self.request("get", "/"), self.project.pk))["item"]
        self.assertEqual(detail["activeNodes"], expected)
        overview = self.data(views.dashboard(self.request("get", "/")))
        self.assertEqual(overview["recentProjects"][0]["activeNodes"], expected)

    def test_filter_matches_either_parallel_branch_before_pagination_without_duplicates(self):
        self.set_active(["early-plan", "budget-match"])
        for stage in ("early-plan", "budget-match"):
            payload = self.list_payload(nodeKey=stage, page=99, pageSize=1, completion="active", search="并行")
            self.assertEqual((payload["total"], payload["page"], payload["totalPages"]), (1, 1, 1))
            self.assertEqual(payload["items"][0]["id"], self.project.pk)
        self.assertEqual(self.list_payload(nodeKey="early-approval")["total"], 0)
        self.assertEqual(self.list_payload(nodeKey="project-filing")["total"], 0)

    def test_later_parallel_branches_are_reported_and_completed_or_disabled_nodes_are_excluded(self):
        for keys in (("early-plan", "project-filing"), ("late-plan", "device-plan"),
                     ("budget", "device-budget"), ("rendering", "tender-plan"), ("layout", "bid-prep")):
            with self.subTest(keys=keys):
                self.set_active(keys)
                self.assertEqual([row["nodeKey"] for row in self.list_payload()["items"][0]["activeNodes"]], list(keys))
                self.project.nodes.filter(node_key=keys[0]).update(status=ProjectNode.STATUS_COMPLETED)
                self.assertEqual([row["nodeKey"] for row in self.list_payload()["items"][0]["activeNodes"]], [keys[1]])
                self.assertEqual(self.list_payload(nodeKey=keys[0])["total"], 0)
                self.project.nodes.filter(node_key=keys[1]).update(enabled=False)
                self.assertEqual(self.list_payload()["items"][0]["activeNodes"], [])
                self.assertEqual(self.list_payload(nodeKey=keys[1])["total"], 0)
                self.project.nodes.update(enabled=True)

    def test_terminal_projects_keep_the_terminal_node_instead_of_old_active_branches(self):
        self.set_active(["early-plan", "budget-match"])
        for status, key in ((ServiceProject.STATUS_COMPLETED, "project-end"),
                            (ServiceProject.STATUS_CANCELLED, "early-plan-result"),
                            (ServiceProject.STATUS_BLOCKED, "early-plan-result")):
            with self.subTest(status=status):
                ServiceProject.objects.filter(pk=self.project.pk).update(status=status, current_node_key=key)
                self.assertEqual(self.list_payload()["items"][0]["activeNodes"], [])
                self.assertEqual(self.list_payload(nodeKey="early-plan")["total"], 0)
                self.assertEqual(self.list_payload(nodeKey=key)["total"], 1)
