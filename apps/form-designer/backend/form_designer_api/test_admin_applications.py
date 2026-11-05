import json
import unittest
from unittest.mock import patch

from .services import list_all_workflow_runs


class AdminApplicationsTests(unittest.TestCase):
    def test_lists_all_applicants_forms_and_statuses_without_redacting(self):
        runs = [
            {"id": "run-new", "applicantUsername": "employee-a", "formId": "rental", "status": "pending",
             "values": {"secret": "完整申请内容"}, "applicantFieldPermissions": [{"fieldId": "secret", "permission": "hidden"}],
             "formSchema": {"id": "rental", "fields": [{"id": "secret", "label": "历史字段"}]}, "tasks": [{"decisions": [{"action": "agree"}]}]},
            {"id": "run-old", "applicantUsername": "employee-b", "formId": "purchase", "status": "completed",
             "formSchema": {"id": "purchase", "fields": []}},
        ]
        with patch("form_designer_api.services.WorkflowRunRepository.list_all", return_value=[(json.dumps(run),) for run in runs]), \
             patch("form_designer_api.services.FormRepository.get_schema") as get_form:
            actual = list_all_workflow_runs()
        self.assertEqual(actual, runs)
        get_form.assert_not_called()

    def test_legacy_records_load_missing_schema_once_per_form(self):
        runs = [{"id": str(i), "formId": "legacy"} for i in range(2)]
        form = {"id": "legacy", "fields": [{"id": "field", "label": "旧字段"}]}
        with patch("form_designer_api.services.WorkflowRunRepository.list_all", return_value=[(json.dumps(run),) for run in runs]), \
             patch("form_designer_api.services.FormRepository.get_schema", return_value=(json.dumps(form),)) as get_form:
            actual = list_all_workflow_runs()
        get_form.assert_called_once_with("legacy")
        self.assertEqual(len(actual), 2)
        self.assertEqual(actual[0]["formSchema"]["fields"], form["fields"])

    def test_deleted_legacy_form_does_not_hide_application(self):
        run = {"id": "run", "formId": "deleted", "values": {"old": "申请内容"}}
        with patch("form_designer_api.services.WorkflowRunRepository.list_all", return_value=[(json.dumps(run),)]), \
             patch("form_designer_api.services.FormRepository.get_schema", return_value=None):
            actual = list_all_workflow_runs()
        self.assertEqual(actual[0]["values"], run["values"])
        self.assertIsNone(actual[0]["formSchema"])


if __name__ == "__main__":
    unittest.main()
