import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from .errors import HTTPException
from pydantic import ValidationError

from .schemas import TaskActionPayload
from .services import evaluate_workflow_route, perform_task_action, task_is_actionable_by_user


class ApprovalRejectionTests(unittest.TestCase):
    def setUp(self):
        self.users = [
            {"username": "first", "displayName": "First", "role": "manager"},
            {"username": "second", "displayName": "Second", "role": "manager"},
        ]
        schema = {"nodes": [
            {"id": "approve", "name": "Approve", "type": "approval", "assignees": ["First", "Second"],
             "approvalButtons": [{"key": "reject", "enabled": True, "opinionMode": "required"}]},
            {"id": "execute", "name": "Execute", "type": "executor", "assignees": ["Second"]},
        ]}
        _, tasks = evaluate_workflow_route(schema, {}, {}, self.users[0], self.users)
        self.run = {"status": "pending", "tasks": tasks}
        # Previously published tasks can still contain a designer's old setting.
        tasks[0]["rejectBehavior"] = "end"
        self.saved = False

    @contextmanager
    def transaction(self):
        yield self

    def get_run_for_update(self, run_id):
        return (run_id, None, "form", "submission", None, json.dumps(self.run))

    def get_submission_values(self, submission_id, form_id):
        return "{}"

    def get_form_schema(self, form_id):
        return '{"fields": []}'

    def save_task_action(self, run_id, submission_id, form_id, run, values, now):
        self.run = run
        self.saved = True

    def reject(self, behavior=None, user=None, comment="拒绝原因"):
        payload = TaskActionPayload(action="reject", rejectBehavior=behavior, comment=comment)
        with patch("form_designer_api.services.WorkflowRunRepository.task_action_transaction", self.transaction):
            return perform_task_action("run", self.run["tasks"][0]["id"], payload, user or self.users[0])

    def test_reviewer_can_return_despite_old_end_setting(self):
        self.reject("return")
        self.assertEqual(self.run["status"], "returned")
        self.assertEqual(self.run["tasks"][0]["status"], "returned")
        self.assertEqual(self.run["tasks"][0]["decisions"][0]["rejectBehavior"], "return")
        self.assertEqual(self.run["tasks"][1]["status"], "cancelled")
        self.assertFalse(task_is_actionable_by_user(self.run["tasks"][0], "second"))

    def test_reviewer_can_end_despite_old_return_setting(self):
        self.run["tasks"][0]["rejectBehavior"] = "return"
        self.reject("end")
        self.assertEqual(self.run["status"], "rejected")
        self.assertEqual(self.run["tasks"][1]["status"], "cancelled")

    def test_rejection_requires_explicit_choice(self):
        with self.assertRaises(HTTPException) as error:
            self.reject()
        self.assertEqual(error.exception.status_code, 422)
        self.assertFalse(self.saved)

    def test_future_reviewer_cannot_reject(self):
        with self.assertRaises(HTTPException) as error:
            self.reject("end", user=self.users[1])
        self.assertEqual(error.exception.status_code, 403)
        self.assertFalse(self.saved)

    def test_required_opinion_is_still_enforced(self):
        with self.assertRaises(HTTPException) as error:
            self.reject("end", comment="")
        self.assertEqual(error.exception.status_code, 422)
        self.assertFalse(self.saved)

    def test_invalid_choice_is_rejected(self):
        with self.assertRaises(ValidationError):
            TaskActionPayload(action="reject", rejectBehavior="continue")


if __name__ == "__main__":
    unittest.main()
