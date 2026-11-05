from __future__ import annotations

import json

from django.test import RequestFactory, TestCase

from . import approval_views
from .approval_models import PresalesApprovalRevision, PresalesApprovalStep
from .models import ProjectNode, ServiceProject
from .services import create_project


class PresalesApprovalApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.project = ServiceProject.objects.create(
            code="PS-APPROVAL-TEST",
            service_type=ServiceProject.TYPE_PRESALES,
            name="售前审批测试项目",
            customer="测试客户",
            current_node_key="early-approval",
        )
        self.node = ProjectNode.objects.create(
            project=self.project,
            node_key="early-approval",
            name="前期立项",
            sequence=1,
            kind="approval",
            status=ProjectNode.STATUS_ACTIVE,
        )

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        admin: bool = True,
        user_id: str = "approval-admin",
        actor_id: str | None = None,
    ):
        method = method.lower()
        if method == "get":
            request = self.factory.get(path)
        elif method == "patch":
            request = self.factory.patch(
                path,
                data=json.dumps(payload or {}, ensure_ascii=False),
                content_type="application/json",
            )
        elif method == "delete":
            request = self.factory.delete(path)
        else:
            request = self.factory.post(
                path,
                data=json.dumps(payload or {}, ensure_ascii=False),
                content_type="application/json",
            )
        request.auth_user_id = user_id
        request.auth_user_name = "审批管理员"
        request.auth_actor_user_id = actor_id or user_id
        request.auth_actor_name = "实际操作人" if actor_id else "审批管理员"
        request.auth_is_proxy = bool(actor_id)
        request.auth_can_use_system_admin = admin and not actor_id
        return request

    @staticmethod
    def data(response) -> dict:
        return json.loads(response.content.decode("utf-8"))

    def collection(self, method: str = "get", payload: dict | None = None, **request_kwargs):
        path = f"/api/after-sales/projects/{self.project.id}/nodes/{self.node.node_key}/approvals"
        return approval_views.presales_approvals(
            self.request(method, path, payload, **request_kwargs),
            self.project.id,
            self.node.node_key,
        )

    def update(self, step_id: int, payload: dict, **request_kwargs):
        path = (
            f"/api/after-sales/projects/{self.project.id}/nodes/"
            f"{self.node.node_key}/approvals/{step_id}"
        )
        return approval_views.presales_approval_item(
            self.request("patch", path, payload, **request_kwargs),
            self.project.id,
            self.node.node_key,
            step_id,
        )

    def delete(self, step_id: int, **request_kwargs):
        path = (
            f"/api/after-sales/projects/{self.project.id}/nodes/"
            f"{self.node.node_key}/approvals/{step_id}"
        )
        return approval_views.presales_approval_item(
            self.request("delete", path, **request_kwargs),
            self.project.id,
            self.node.node_key,
            step_id,
        )

    def test_collection_initializes_two_prototype_approval_rows(self):
        response = self.collection()

        self.assertEqual(response.status_code, 200, self.data(response))
        items = self.data(response)["items"]
        self.assertEqual([item["title"] for item in items], ["组长审批", "区域经理审批"])
        self.assertEqual([item["approverName"] for item in items], ["组长-陈明", "区域经理-周宁"])
        self.assertTrue(all(item["status"] == "pending" for item in items))
        self.assertTrue(all(item["revision"] == 1 for item in items))
        self.assertEqual(
            PresalesApprovalRevision.objects.filter(step__node=self.node).count(),
            2,
        )
        self.node.refresh_from_db()
        self.assertEqual(
            [row["title"] for row in self.node.business_data["approvalSteps"]],
            ["组长审批", "区域经理审批"],
        )

        repeated = self.collection()
        self.assertEqual(repeated.status_code, 200, self.data(repeated))
        self.assertEqual(PresalesApprovalStep.objects.filter(node=self.node).count(), 2)
        self.assertEqual(
            PresalesApprovalRevision.objects.filter(step__node=self.node).count(),
            2,
        )

    def test_each_save_appends_an_immutable_traceable_revision(self):
        first = self.data(self.collection())["items"][0]
        approved = self.update(first["id"], {
            "title": "组长审批",
            "approverUserId": "leader-chen",
            "approverName": "组长-陈明",
            "status": "approved",
            "opinion": "同意进入下一阶段。",
            "expectedRevision": 1,
        })
        self.assertEqual(approved.status_code, 200, self.data(approved))
        approved_item = self.data(approved)["item"]
        self.assertEqual(approved_item["revision"], 2)
        self.assertEqual(approved_item["status"], "approved")
        self.assertTrue(approved_item["decidedAt"])

        rejected = self.update(first["id"], {
            "status": "rejected",
            "opinion": "客户预算依据不足，请补充。",
            "expectedRevision": 2,
        })
        self.assertEqual(rejected.status_code, 200, self.data(rejected))
        item = self.data(rejected)["item"]
        self.assertEqual(item["revision"], 3)
        self.assertEqual(item["status"], "rejected")
        self.assertEqual([row["revision"] for row in item["history"]], [3, 2, 1])
        self.assertEqual(item["history"][1]["approverUserId"], "leader-chen")
        self.assertEqual(item["history"][1]["opinion"], "同意进入下一阶段。")
        self.assertTrue(all(row["recordedAt"] for row in item["history"]))
        self.assertTrue(all(row["recordedByName"] for row in item["history"]))
        self.node.refresh_from_db()
        snapshot = self.node.business_data["approvalSteps"][0]
        self.assertEqual(snapshot["status"], "rejected")
        self.assertEqual(snapshot["opinion"], "客户预算依据不足，请补充。")

    def test_rejection_requires_opinion_and_revision_conflicts_are_rejected(self):
        first = self.data(self.collection())["items"][0]

        missing_opinion = self.update(first["id"], {
            "status": "rejected",
            "opinion": "",
            "expectedRevision": 1,
        })
        self.assertEqual(missing_opinion.status_code, 400, self.data(missing_opinion))
        self.assertEqual(self.data(missing_opinion)["code"], "APPROVAL_OPINION_REQUIRED")

        saved = self.update(first["id"], {
            "status": "approved",
            "opinion": "同意",
            "expectedRevision": 1,
        })
        self.assertEqual(saved.status_code, 200, self.data(saved))

        conflict = self.update(first["id"], {
            "status": "approved",
            "opinion": "覆盖他人意见",
            "expectedRevision": 1,
        })
        self.assertEqual(conflict.status_code, 409, self.data(conflict))
        self.assertEqual(self.data(conflict)["code"], "APPROVAL_REVISION_CONFLICT")

    def test_additional_approval_row_persists_assignee_result_opinion_and_time(self):
        self.collection()
        response = self.collection("post", {
            "title": "总经理审批",
            "approverUserId": "general-manager-zhao",
            "approverName": "总经理-赵总",
            "status": "approved",
            "opinion": "同意立项。",
        })

        self.assertEqual(response.status_code, 201, self.data(response))
        item = self.data(response)["item"]
        self.assertEqual(item["sequence"], 3)
        self.assertEqual(item["approverUserId"], "general-manager-zhao")
        self.assertEqual(item["status"], "approved")
        self.assertEqual(item["opinion"], "同意立项。")
        self.assertTrue(item["decidedAt"])
        self.assertEqual(item["history"][0]["revision"], 1)

    def test_pending_approval_rows_can_be_deleted_and_sequences_are_compacted(self):
        defaults = self.data(self.collection())["items"]
        third = self.data(self.collection("post", {
            "title": "财务审批",
            "approverName": "财务经理",
            "status": "pending",
        }))["item"]
        fourth = self.data(self.collection("post", {
            "title": "总经理审批",
            "approverName": "总经理",
            "status": "pending",
        }))["item"]

        response = self.delete(third["id"])

        self.assertEqual(response.status_code, 200, self.data(response))
        items = self.data(response)["items"]
        self.assertEqual([item["id"] for item in items], [defaults[0]["id"], defaults[1]["id"], fourth["id"]])
        self.assertEqual([item["sequence"] for item in items], [1, 2, 3])
        self.assertFalse(PresalesApprovalStep.objects.filter(pk=third["id"]).exists())
        self.node.refresh_from_db()
        self.assertEqual([item["sequence"] for item in self.node.business_data["approvalSteps"]], [1, 2, 3])

        default_deleted = self.delete(defaults[0]["id"])
        self.assertEqual(default_deleted.status_code, 200, self.data(default_deleted))
        self.assertEqual(
            [item["id"] for item in self.data(default_deleted)["items"]],
            [defaults[1]["id"], fourth["id"]],
        )
        self.assertEqual([item["sequence"] for item in self.data(default_deleted)["items"]], [1, 2])

        self.assertEqual(self.delete(defaults[1]["id"]).status_code, 200)
        self.assertEqual(self.delete(fourth["id"]).status_code, 200)
        repeated = self.collection()
        self.assertEqual(repeated.status_code, 200, self.data(repeated))
        self.assertEqual(self.data(repeated)["items"], [])

    def test_only_admin_and_presales_approval_nodes_are_allowed(self):
        denied = self.collection(admin=False, user_id="ordinary-user")
        self.assertEqual(denied.status_code, 403, self.data(denied))
        self.assertEqual(self.data(denied)["code"], "APP_ADMIN_REQUIRED")

        midsales = ServiceProject.objects.create(
            code="MS-APPROVAL-TEST",
            service_type=ServiceProject.TYPE_MIDSALES,
            name="售中项目",
            customer="测试客户",
            current_node_key="midsales-project",
        )
        node = ProjectNode.objects.create(
            project=midsales,
            node_key="midsales-project",
            name="项目立项",
            sequence=1,
            kind="approval",
            status=ProjectNode.STATUS_ACTIVE,
        )
        path = f"/api/after-sales/projects/{midsales.id}/nodes/{node.node_key}/approvals"
        invalid = approval_views.presales_approvals(
            self.request("get", path),
            midsales.id,
            node.node_key,
        )
        self.assertEqual(invalid.status_code, 409, self.data(invalid))
        self.assertEqual(self.data(invalid)["code"], "PRESALES_APPROVAL_NODE_REQUIRED")

    def test_new_presales_projects_initialize_approval_rows(self):
        request = self.request("post", "/api/after-sales/projects")
        project = create_project(request, {
            "code": "PS-NEW-APPROVAL",
            "service_type": ServiceProject.TYPE_PRESALES,
            "name": "新售前项目",
            "customer": "新客户",
        })

        approval_nodes = project.nodes.filter(node_key__in=["early-approval", "late-approval"])
        self.assertEqual(approval_nodes.count(), 2)
        self.assertEqual(
            PresalesApprovalStep.objects.filter(node__in=approval_nodes).count(),
            4,
        )
        self.assertEqual(
            PresalesApprovalRevision.objects.filter(step__node__in=approval_nodes).count(),
            4,
        )
