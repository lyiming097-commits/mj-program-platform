import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from .errors import HTTPException

from .schemas import TaskActionPayload
from .services import evaluate_workflow_route, perform_task_action, task_is_actionable_by_user


class ExecutorSequenceTests(unittest.TestCase):
    def setUp(self):
        self.users = [
            {"username": "first", "displayName": "First", "role": "employee"},
            {"username": "second", "displayName": "Second", "role": "employee"},
        ]
        schema = {"nodes": [
            {"id": "execute", "name": "Execute", "type": "executor", "assignees": ["First", "Second"]},
            {"id": "next", "name": "Next", "type": "executor", "assignees": ["First"]},
        ]}
        _, tasks = evaluate_workflow_route(schema, {}, {}, self.users[0], self.users)
        self.run = {"status": "pending", "tasks": tasks}
        self.saved = []
        self.task_id = tasks[0]["id"]

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
        self.saved.append(run_id)

    def complete(self, user, task_id=None):
        with patch("form_designer_api.services.WorkflowRunRepository.task_action_transaction", self.transaction):
            return perform_task_action("run", task_id or self.task_id, TaskActionPayload(action="complete"), user)

    def test_members_execute_in_order_and_only_then_advance(self):
        self.assertTrue(task_is_actionable_by_user(self.run["tasks"][0], "first"))
        self.assertFalse(task_is_actionable_by_user(self.run["tasks"][0], "second"))
        with self.assertRaises(HTTPException) as rejected:
            self.complete(self.users[1])
        self.assertEqual(rejected.exception.status_code, 403)
        self.assertEqual(self.saved, [])

        self.complete(self.users[0])
        task, next_task = self.run["tasks"]
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["activeAssigneeIndex"], 1)
        self.assertEqual(task["assigneeProgress"]["first"], "completed")
        self.assertEqual(next_task["status"], "waiting")
        with self.assertRaises(HTTPException):
            self.complete(self.users[0])

        self.complete(self.users[1])
        self.assertEqual(self.run["tasks"][0]["status"], "completed")
        self.assertEqual(self.run["tasks"][1]["status"], "pending")
        self.complete(self.users[0], self.run["tasks"][1]["id"])
        self.assertEqual(self.run["status"], "completed")

    def test_existing_executor_tasks_keep_their_original_behavior(self):
        self.run["tasks"][0].pop("executionMode")
        self.assertTrue(task_is_actionable_by_user(self.run["tasks"][0], "second"))
        self.complete(self.users[1])
        self.assertEqual(self.run["tasks"][0]["status"], "completed")
        self.assertEqual(self.run["tasks"][1]["status"], "pending")

    def test_direct_manager_executor_falls_back_to_general_manager(self):
        boss = {"username": "boss", "displayName": "Boss", "role": "general_manager"}
        schema = {"nodes": [{"id": "execute", "type": "executor", "assigneeMode": "direct_manager"}]}
        _, tasks = evaluate_workflow_route(schema, {}, {}, self.users[0], [*self.users, boss])
        self.assertEqual(tasks[0]["assignees"], ["boss"])
        self.assertEqual(tasks[0]["executionMode"], "sequential")


if __name__ == "__main__":
    unittest.main()
