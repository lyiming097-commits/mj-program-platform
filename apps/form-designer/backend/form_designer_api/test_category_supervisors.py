from django.test import TestCase

from .errors import HTTPException
from .models import CategorySupervisorState
from .services import evaluate_workflow_route, validate_workflow_for_publish


class CategoryRoutingTests(TestCase):
    def setUp(self):
        self.users = [
            {'username': 'applicant', 'displayName': '申请人', 'role': 'employee', 'department': '研发', 'managerUsername': 'org-boss'},
            {'username': 'org-boss', 'displayName': '组织主管', 'role': 'manager', 'department': '研发'},
            {'username': 'sales-boss', 'displayName': '销售主管', 'role': 'employee', 'department': '销售'},
            {'username': 'finance-boss', 'displayName': '财务主管', 'role': 'employee', 'department': '财务'},
        ]
        CategorySupervisorState.objects.create(assignments={'销售流程': ['sales-boss'], '财务流程': ['finance-boss']})

    def route(self, category, nodes=None):
        return evaluate_workflow_route({'category': category, 'nodes': nodes or [
            {'id': 'approve', 'type': 'approval', 'name': '主管审批', 'assigneeMode': 'direct_manager'},
        ]}, {}, {}, self.users[0], self.users)[1]

    def test_approval_direct_manager_uses_workflow_category_instead_of_applicant_department(self):
        self.assertEqual(self.route('销售流程')[0]['assignees'], ['sales-boss'])
        self.assertEqual(self.route('财务流程')[0]['assignees'], ['finance-boss'])
        self.assertEqual(self.route('销售流程')[0]['assigneeMode'], 'direct_manager')

    def test_repeated_nodes_share_one_consistent_category_read_and_independent_assignee_lists(self):
        nodes = [{'id': str(index), 'type': 'approval', 'assigneeMode': 'direct_manager'} for index in range(3)]
        with self.assertNumQueries(1):
            tasks = self.route('销售流程', nodes)
        tasks[0]['assignees'].clear()
        self.assertEqual(tasks[1]['assignees'], ['sales-boss'])

    def test_unmatched_branch_does_not_require_a_supervisor(self):
        nodes = [{'id': 'condition', 'type': 'condition', 'branches': [
            {'fieldId': 'amount', 'operator': 'gt', 'value': '100', 'nodes': [{'type': 'approval', 'assigneeMode': 'direct_manager'}]},
            {'isDefault': True, 'nodes': []},
        ]}]
        with self.assertNumQueries(0):
            self.assertEqual(self.route('未配置', nodes), [])

    def test_missing_and_unavailable_category_supervisors_fail_closed(self):
        with self.assertRaises(HTTPException) as error:
            self.route('未配置')
        self.assertEqual(error.exception.status_code, 422)
        self.users = [user for user in self.users if user['username'] != 'sales-boss']
        with self.assertRaises(HTTPException) as error:
            self.route('销售流程')
        self.assertEqual(error.exception.status_code, 422)

    def test_publish_requires_supervisors_for_all_direct_manager_approval_branches(self):
        schema = {'category': '未配置', 'nodes': [
            {'type': 'start'},
            {'type': 'approval', 'name': '直属主管', 'assigneeMode': 'direct_manager', 'approvalButtons': [{'key': 'agree', 'enabled': True}]},
            {'type': 'end'},
        ]}
        self.assertTrue(any('尚未设置分类主管' in error for error in validate_workflow_for_publish(schema, {}, self.users)))
        schema['category'] = '销售流程'
        self.assertEqual(validate_workflow_for_publish(schema, {}, self.users), [])

    def test_category_changes_do_not_modify_previously_resolved_tasks(self):
        old_tasks = self.route('销售流程')
        CategorySupervisorState.objects.update(assignments={'销售流程': ['finance-boss']})
        self.assertEqual(old_tasks[0]['assignees'], ['sales-boss'])
        self.assertEqual(self.route('销售流程')[0]['assignees'], ['finance-boss'])
