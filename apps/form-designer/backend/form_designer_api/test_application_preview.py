import json
import unittest
from contextlib import nullcontext
from copy import deepcopy
from unittest.mock import patch

from django.test import RequestFactory
from . import services, views
from .errors import HTTPException
from .schemas import WorkflowRunPayload


class ApplicationPreviewTests(unittest.TestCase):
    def setUp(self):
        self.user = {"username": "employee-a", "displayName": "申请人", "department": "技术部"}
        self.form = {"id": "form", "fields": [
            {"id": "reason", "type": "text", "label": "申请事由", "required": True},
            {"id": "amount", "type": "number", "label": "金额"},
            {"id": "dates", "type": "dateRange", "label": "申请日期"},
        ], "permissions": {"accessMode": "all", "canSubmit": True}}
        self.workflow = {"id": "workflow", "nodes": [{"type": "approval", "name": "未发布的新节点"}],
            "publishedSnapshot": {"version": 3, "formId": "form", "formSchema": self.form, "nodes": [
                {"id": "a", "type": "approval", "name": "主管审批", "assignees": ["approver"]},
                {"id": "c", "type": "condition", "name": "内部条件", "branches": [
                    {"id": "high", "name": "保密分支名", "fieldId": "amount", "operator": "gt", "value": "1000", "nodes": [
                        {"id": "b", "type": "approval", "name": "复核审批", "assignees": ["approver"]}]},
                    {"id": "default", "isDefault": True, "nodes": []},
                ]},
            ]}}
        self.patches = [
            patch("form_designer_api.services.load_workflow", side_effect=lambda _: deepcopy(self.workflow)),
            patch("form_designer_api.services.UserRepository.list_active_for_routing", return_value=[("approver", "主管", "manager", "技术部", None)]),
            patch("form_designer_api.services.WorkflowRunRepository.create_run"),
        ]
        self.mocks = [item.start() for item in self.patches]
        for item in self.patches:
            self.addCleanup(item.stop)

    def preview(self, **values):
        return services.preview_workflow_run("workflow", WorkflowRunPayload(values=values), self.user)

    def test_uses_published_nodes_without_creating_run_or_exposing_config(self):
        actual = self.preview(reason="测试", amount="2000")
        self.assertEqual(actual["version"], 3)
        self.assertFalse(actual["incomplete"])
        self.assertEqual(actual["steps"], [
            {"name": "主管审批", "type": "approval", "assigneeNames": ["主管"]},
            {"name": "复核审批", "type": "approval", "assigneeNames": ["主管"]},
        ])
        self.assertEqual(set(actual), {"version", "incomplete", "steps"})
        self.assertNotIn("保密分支名", json.dumps(actual, ensure_ascii=False))
        self.mocks[2].assert_not_called()

    def test_recalculates_condition_for_current_values(self):
        self.assertEqual(len(self.preview(reason="测试", amount=100)["steps"]), 1)
        self.assertEqual(len(self.preview(reason="测试", amount=2000)["steps"]), 2)

    def test_copy_in_nested_branch_is_visible_only_after_the_node_is_reached(self):
        snapshot = self.workflow["publishedSnapshot"]
        snapshot["applicantFieldPermissions"] = [{"fieldId": "dates", "permission": "hidden"}]
        snapshot["nodes"][1]["branches"][0]["nodes"] = [{
            "id": "nested", "type": "condition", "branches": [
                {"id": "copy-path", "fieldId": "amount", "operator": "gt", "value": "1500", "nodes": [
                    {"id": "copy", "type": "cc", "name": "抄送财务", "assignees": ["employee-b"]},
                ]},
                {"id": "default", "isDefault": True, "nodes": []},
            ],
        }]
        self.mocks[1].return_value.append(("employee-b", "财务成员", "employee", "财务部", None))
        recipient = {"username": "employee-b"}
        services.start_workflow_run("workflow", WorkflowRunPayload(values={"reason": "测试", "amount": 2000}), self.user)
        run = self.mocks[2].call_args.args[0]
        approval, copy = run["tasks"]
        self.assertEqual(copy["status"], "waiting")
        with patch.object(services, "approval_record_schemas", return_value=[run]):
            self.assertEqual(services.list_approval_records(recipient, "personal"), [])
            with self.assertRaises(HTTPException):
                services.get_approval_record(run["id"], recipient)
            approval["status"] = "completed"
            run["status"] = services.advance_workflow_tasks(run["tasks"])
            self.assertEqual(run["status"], "completed")
            record = services.list_approval_records(recipient, "personal")[0]
            self.assertTrue(record["copied"])
            self.assertFalse(record["canHandle"])
            detail = services.get_approval_record(run["id"], recipient)
            self.assertEqual(detail["values"]["reason"], "测试")
            self.assertNotIn("dates", {field["id"] for field in detail["formSchema"]["fields"]})

    def test_unfinished_form_is_marked_incomplete(self):
        self.assertTrue(self.preview()["incomplete"])
        self.assertEqual(len(self.preview()["steps"]), 1)

    def test_proxy_submitter_can_find_only_their_delegated_record(self):
        self.workflow["publishedSnapshot"]["applicantFieldPermissions"] = [{"fieldId": "dates", "permission": "hidden"}]
        proxy = {"username": "employee-b"}
        result = services.start_workflow_run(
            "workflow", WorkflowRunPayload(values={"reason": "测试"}),
            {**self.user, "actorUserId": proxy["username"]},
        )
        run = self.mocks[2].call_args.args[0]
        self.assertNotIn("submittedByActorId", result)
        with patch.object(services, "approval_record_schemas", return_value=[run]):
            self.assertEqual(services.list_approval_records(proxy), [])
            record, = services.list_approval_records(proxy, "personal")
            self.assertTrue(record["delegated"])
            self.assertFalse(record["mine"])
            self.assertEqual(record["taskArrivedAt"], run["createdAt"])
            detail = services.get_approval_record(run["id"], proxy)
            self.assertFalse(detail["canRecall"])
            self.assertNotIn("submittedByActorId", detail)
            self.assertNotIn("dates", {field["id"] for field in detail["formSchema"]["fields"]})
            self.assertEqual(services.list_approval_records({"username": "other"}, "personal"), [])
            run["formSchema"]["permissions"]["canViewOwnRecords"] = False
            self.assertEqual(services.list_approval_records(proxy, "personal"), [])
            with self.assertRaises(HTTPException):
                services.get_approval_record(run["id"], proxy)

    def test_unknown_field_rejected(self):
        with self.assertRaises(HTTPException) as context:
            self.preview(secret="bad")
        self.assertEqual(context.exception.status_code, 422)

    def test_form_access_and_submission_permission_enforced(self):
        self.form["permissions"] = {"accessMode": "members", "members": ["other"]}
        with self.assertRaises(HTTPException) as context:
            self.preview()
        self.assertEqual(context.exception.status_code, 403)
        self.form["permissions"] = {"canSubmit": False}
        with self.assertRaises(HTTPException) as context:
            self.preview()
        self.assertEqual(context.exception.status_code, 403)

    def test_hidden_and_readonly_defaults_cannot_be_overridden(self):
        self.form["fields"][1]["defaultValue"] = "2000"
        for permission in ["hidden", "readonly"]:
            self.workflow["publishedSnapshot"]["applicantFieldPermissions"] = [{"fieldId": "amount", "permission": permission}]
            self.assertEqual(len(self.preview(reason="测试", amount=0)["steps"]), 2)

    def test_confirmation_cannot_submit_a_newer_version_than_previewed(self):
        preview = self.preview(reason="测试", amount=100)
        payload = WorkflowRunPayload(values={"reason": "测试", "amount": 100}, expectedVersion=preview["version"])
        self.workflow["publishedSnapshot"]["version"] += 1
        with self.assertRaises(HTTPException) as context:
            services.start_workflow_run("workflow", payload, self.user)
        self.assertEqual(context.exception.status_code, 409)
        self.mocks[2].assert_not_called()

        payload.expectedVersion += 1
        result = services.start_workflow_run("workflow", payload, self.user)
        self.assertEqual(result["workflowVersion"], payload.expectedVersion)
        self.mocks[2].assert_called_once()

    def test_unpublished_workflow_is_rejected(self):
        del self.workflow["publishedSnapshot"]
        with self.assertRaises(HTTPException) as context:
            self.preview()
        self.assertEqual(context.exception.status_code, 409)

    def test_date_range_submission_requires_both_dates_and_order(self):
        self.form["fields"][2]["required"] = True
        for value in [["2026-11-03", ""], ["", ""], ["2026-11-05", "2026-11-03"], ["2026-02-30", "2026-03-01"]]:
            with self.assertRaises(HTTPException) as context:
                services.start_workflow_run("workflow", WorkflowRunPayload(values={"reason": "测试", "dates": value}), self.user)
            self.assertEqual(context.exception.status_code, 422)
        self.mocks[2].assert_not_called()

    def test_half_filled_date_range_can_be_previewed_but_is_incomplete(self):
        self.assertTrue(self.preview(reason="测试", amount=10, dates=["2026-11-03", ""])["incomplete"])

    def test_readonly_date_range_uses_normalized_published_default(self):
        self.form["fields"][2].update(required=True, defaultValue="2026-11-03 至 2026-11-05")
        self.workflow["publishedSnapshot"]["applicantFieldPermissions"] = [{"fieldId": "dates", "permission": "readonly"}]
        result = services.start_workflow_run("workflow", WorkflowRunPayload(values={"reason": "测试", "dates": ["2030-01-01", "2030-01-02"]}), self.user)
        self.assertEqual(result["values"]["dates"], ["2026-11-03", "2026-11-05"])

    def test_preview_http_route_has_no_audit_or_submission_write(self):
        request = RequestFactory().post("/api/form-designer/workflows/workflow/preview", data=json.dumps({"values": {"reason": "测试", "amount": 100}}), content_type="application/json")
        request.auth_user_id = self.user["username"]
        with patch.object(views.handlers, "load_workflow", return_value=self.workflow), patch.object(views, "capabilities", return_value={"user"}), patch.object(views, "current_user", return_value=self.user), patch.object(views.transaction, "atomic", return_value=nullcontext()), patch.object(views, "audit") as audit:
            response = views.endpoint(request, "workflows/workflow/preview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["steps"][0]["name"], "主管审批")
        audit.assert_not_called()
        self.mocks[2].assert_not_called()


if __name__ == "__main__":
    unittest.main()
