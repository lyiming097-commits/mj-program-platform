"""PostgreSQL regression: an applicant recall and a final approval serialize."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from .errors import HTTPException
from .models import Form, WorkflowRun
from .repositories import WorkflowRunRepository, WorkflowTaskUnitOfWork, utc_now
from .schemas import TaskActionPayload, WorkflowRecallPayload
from .services import perform_task_action, recall_workflow_run


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL row locks')
class WorkflowRecallConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = {'username': 'owner', 'displayName': 'Applicant'}
        self.reviewer = {'username': 'reviewer', 'displayName': 'Reviewer'}
        now = utc_now()
        Form.objects.create(id='recall-form', schema_json=json.dumps({'id': 'recall-form', 'fields': []}), updated_at=now)
        self.run = {
            'id': 'recall-run', 'workflowId': 'recall-flow', 'workflowVersion': 1,
            'formId': 'recall-form', 'submissionId': 'recall-submission',
            'title': 'Concurrent recall', 'applicant': 'Applicant', 'applicantUsername': 'owner',
            'status': 'pending', 'values': {}, 'createdAt': now,
            'tasks': [{
                'id': 'review', 'nodeType': 'approval', 'status': 'pending',
                'assignees': ['reviewer'], 'assigneeNames': ['Reviewer'],
                'approvalMode': 'sequential', 'assigneeProgress': {'reviewer': 'pending'},
                'approvalButtons': [{'key': 'agree', 'enabled': True}], 'decisions': [],
            }],
        }
        WorkflowRunRepository.create_run(self.run, now)

    def race(self, first_action):
        locked, attempted, release = threading.Event(), threading.Event(), threading.Event()
        original = WorkflowTaskUnitOfWork.get_run_for_update

        def controlled_lock(repository, run_id):
            first = threading.current_thread().name == 'first-action'
            if not first:
                attempted.set()
            row = original(repository, run_id)
            if first:
                locked.set()
                if not release.wait(10):
                    raise RuntimeError('Timed out waiting to release test lock')
            return row

        def invoke(action, name):
            threading.current_thread().name = name
            close_old_connections()
            try:
                if action == 'recall':
                    return recall_workflow_run('recall-run', WorkflowRecallPayload(comment='Cancel'), self.owner)['runStatus']
                return perform_task_action('recall-run', 'review', TaskActionPayload(action='agree'), self.reviewer)['runStatus']
            except HTTPException as error:
                return error.status_code
            finally:
                close_old_connections()

        with patch.object(WorkflowTaskUnitOfWork, 'get_run_for_update', controlled_lock):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(invoke, first_action, 'first-action')
                try:
                    self.assertTrue(locked.wait(10))
                    second = pool.submit(invoke, 'approve' if first_action == 'recall' else 'recall', 'second-action')
                    self.assertTrue(attempted.wait(10))
                    self.assertFalse(second.done())
                finally:
                    release.set()
                return first.result(timeout=10), second.result(timeout=10)

    def test_recall_wins_final_approval_cannot_restore_task(self):
        self.assertEqual(self.race('recall'), ('recalled', 409))
        row = WorkflowRun.objects.get(pk='recall-run')
        run = json.loads(row.result_json)
        self.assertEqual(row.status, 'recalled')
        self.assertEqual(run['tasks'][0]['status'], 'cancelled')
        self.assertEqual(run['tasks'][0]['decisions'], [])

    def test_final_approval_wins_recall_cannot_overwrite_decision(self):
        self.assertEqual(self.race('approve'), ('completed', 409))
        row = WorkflowRun.objects.get(pk='recall-run')
        run = json.loads(row.result_json)
        self.assertEqual(row.status, 'completed')
        self.assertEqual(run['tasks'][0]['status'], 'completed')
        self.assertEqual(run['tasks'][0]['decisions'][0]['action'], 'agree')
        self.assertNotIn('recall', run)
