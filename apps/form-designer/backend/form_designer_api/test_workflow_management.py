import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from . import views
from .models import Form, Workflow, WorkflowRun


class WorkflowManagementTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.people = [
            {'username': 'admin', 'displayName': '总管理员', 'role': 'admin'},
            {'username': 'manager', 'displayName': '流程管理员', 'role': 'employee'},
            {'username': 'replacement', 'displayName': '接替人员', 'role': 'employee'},
        ]
        for target in ('permissions.routing_users', 'views.routing_users', 'handlers.routing_users',
                       'workflow_personnel.routing_users'):
            mock = patch('form_designer_api.' + target, return_value=self.people)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch('form_designer_api.category_supervisors.organization_snapshot',
                     return_value=([], [{'userId': item['username']} for item in self.people], 7))
        mock.start()
        self.addCleanup(mock.stop)

    def call(self, resource, method='get', data=None, user='admin', **headers):
        request = getattr(self.factory, method)('/' + resource, data=data or {}, content_type='application/json', **headers) if method != 'get' else self.factory.get('/' + resource, data or {})
        request.auth_user_id = user
        request.auth_can_use_system_admin = user == 'admin'
        with patch.object(views, 'capabilities', return_value={'admin', 'designer', 'user'} if user == 'admin' else {'user'}):
            response = views.endpoint(request, resource)
        return response.status_code, json.loads(response.content)

    def save_category(self, **overrides):
        return self.call('workflow-category-settings', 'post', {
            'name': '测试流程', 'administratorUserIds': ['manager'], 'supervisorUserIds': [],
            'revision': '1', 'orgRevision': '7', **overrides,
        })

    def test_category_creation_rename_and_scoped_approval_management(self):
        status, category = self.save_category()
        self.assertEqual(status, 200)
        self.assertEqual(Workflow.objects.count(), 0)
        status, created = self.call('approvals', 'post', {
            'name': '测试申请', 'category': category['key'], 'assignees': ['replacement'],
        }, user='manager')
        self.assertEqual(status, 201)
        workflow = created['workflow']
        renamed, result = self.save_category(key=category['key'], name='更新后的分类', revision='2')
        self.assertEqual((renamed, result['key']), (200, category['key']))
        self.assertIn(result, self.call('workflow-categories', user='manager')[1])
        self.assertEqual(self.call('workflows/' + workflow['id'], user='manager')[0], 200)
        self.assertEqual(self.call('workflows/' + workflow['id'] + '/disable', 'post', user='manager')[0], 200)
        self.assertEqual(self.call('workflows/' + workflow['id'], 'put', {**workflow, 'category': '财务流程'}, user='manager')[0], 403)
        self.assertEqual(self.call('approvals', 'post', {'name': '越权申请', 'category': '财务流程', 'assignees': ['replacement']}, user='manager')[0], 403)
        self.assertEqual(self.call('workflow-category-settings', user='manager')[0], 403)
        self.assertEqual(self.call('workflow-personnel', user='manager')[0], 403)

    def test_card_rename_updates_linked_form_and_published_name(self):
        _, category = self.save_category()
        _, created = self.call('approvals', 'post', {
            'name': '原流程', 'category': category['key'], 'assignees': ['replacement'],
        }, user='manager')
        form = created['form']
        route = 'workflows/' + created['workflow']['id']
        routing_people = [(item['username'], item['displayName'], item['role'], '', '') for item in self.people]
        with patch('form_designer_api.services.UserRepository.list_active_for_routing', return_value=routing_people):
            published, workflow = self.call(route + '/publish', 'post', user='manager')
        self.assertEqual(published, 200)
        payload = {'name': '  新流程名  ', 'updatedAt': workflow['updatedAt']}
        self.assertEqual(self.call(route + '/name', 'patch', payload, user='replacement')[0], 403)
        status, renamed = self.call(route + '/name', 'patch', payload, user='manager')
        self.assertEqual(status, 200)
        saved = renamed['workflow']
        self.assertEqual((saved['name'], saved['publishedSnapshot']['name'],
                          saved['publishedSnapshot']['formSchema']['name']), ('新流程名',) * 3)
        self.assertEqual(saved['publishedVersion'], workflow['publishedVersion'])
        self.assertEqual(saved.get('draftSavedAt'), workflow.get('draftSavedAt'))
        self.assertEqual(json.loads(Form.objects.get(pk=form['id']).schema_json)['name'], '新流程名')
        self.assertEqual(self.call(route + '/name', 'patch', payload, user='manager')[0], 409)

    def test_recycled_group_hides_its_workflows_until_restored(self):
        _, category = self.save_category()
        _, created = self.call('approvals', 'post', {
            'name': '所属流程', 'category': category['key'], 'assignees': ['replacement'],
        }, user='manager')
        workflow = created['workflow']
        route = 'workflow-category-settings/lifecycle'
        delete = {'key': category['key'], 'action': 'delete', 'revision': '2'}
        self.assertEqual(self.call(route, 'post', delete, user='manager')[0], 403)
        self.assertEqual(self.call(route, 'post', {**delete, 'revision': '1'})[0], 409)
        status, archived = self.call(route, 'post', delete)
        self.assertEqual(status, 200)
        self.assertTrue(archived['deletedAt'])
        self.assertIn(archived, self.call('workflow-categories')[1])
        self.assertEqual(self.call('workflows', user='manager')[1], [])
        self.assertEqual(self.call('workflows/' + workflow['id'] + '/preview', 'post', {'values': {}})[0], 409)
        self.assertEqual(self.call(route, 'post', {**delete, 'action': 'restore'})[0], 200)
        restored_status, restored = self.call('workflows/' + workflow['id'], user='manager')
        self.assertEqual((restored_status, restored['name'], restored['updatedAt']),
                         (200, workflow['name'], workflow['updatedAt']))

    def test_personnel_replacement_keeps_published_and_running_references(self):
        node = {'id': 'review', 'name': '合同复核', 'type': 'approval', 'assigneeMode': 'specified', 'assignees': ['former']}
        workflow = {'id': 'contract', 'name': '合同审批', 'category': '销售流程', 'updatedAt': '2026-11-01',
                    'nodes': [node], 'publishedSnapshot': {'version': 4, 'category': '销售流程', 'nodes': [node]}}
        Workflow.objects.create(id='contract', schema_json=json.dumps(workflow), updated_at=workflow['updatedAt'])
        run = {'id': 'run', 'title': '合同申请', 'workflowName': '合同审批', 'workflowCategory': '销售流程',
               'tasks': [{'id': 'task', 'status': 'pending', 'nodeName': '合同复核',
                          'assignees': ['former'], 'assigneeNames': ['张伟']}]}
        WorkflowRun.objects.create(id='run', workflow_id='contract', workflow_version=4, form_id='form',
                                   submission_id='submission', status='pending', result_json=json.dumps(run))
        status, impact = self.call('workflow-personnel', data={'userId': 'former'})
        self.assertEqual(status, 200)
        self.assertEqual((impact['person']['name'], impact['person']['active']), ('张伟', False))
        self.assertEqual(len(impact['templates']), 1)
        self.assertEqual(len(impact['runs']), 1)
        selected = {'workflowId': 'contract', 'nodeId': 'review', 'updatedAt': '2026-11-01'}
        request = {'source': 'former', 'target': 'replacement', 'nodes': [selected]}
        self.assertEqual(self.call('workflow-personnel', 'post', request), (200, {'replaced': 1}))
        self.assertEqual(self.call('workflow-personnel', 'post', request)[0], 409)
        saved = json.loads(Workflow.objects.get(pk='contract').schema_json)
        self.assertEqual(saved['nodes'][0]['assignees'], ['replacement'])
        self.assertEqual(saved['publishedSnapshot']['nodes'][0]['assignees'], ['former'])
        self.assertEqual(json.loads(WorkflowRun.objects.get(pk='run').result_json), run)
        self.assertEqual(self.call('workflows/contract', 'put', saved, HTTP_X_WORKFLOW_UPDATED_AT='2026-11-01')[0], 409)

    def test_personnel_search_returns_complete_workflow_and_saves_any_assignee_live(self):
        review = {'id': 'review', 'name': '合同复核', 'type': 'approval', 'assignees': ['former']}
        execution = {'id': 'execute', 'name': '合同归档', 'type': 'executor', 'assignees': ['manager', 'admin']}
        copy = {'id': 'copy', 'name': '抄送销售', 'type': 'cc', 'assignees': ['manager']}
        nodes = [
            {'id': 'start', 'type': 'start', 'formId': 'form'},
            {'id': 'condition', 'type': 'condition', 'branches': [{'id': 'high', 'name': '高金额', 'nodes': [review]}]},
            execution, copy, {'id': 'end', 'type': 'end'},
        ]
        schema = {
            'id': 'sales', 'name': '尚未发布的名称修改', 'category': '销售流程', 'updatedAt': '2026-11-01',
            'draftSavedAt': '2026-11-01', 'nodes': nodes,
            'publishedSnapshot': {'version': 4, 'name': '销售合同审批', 'category': '销售流程', 'nodes': nodes},
        }
        Workflow.objects.create(id='sales', schema_json=json.dumps(schema), updated_at=schema['updatedAt'])
        run = {'id': 'old-run', 'tasks': [{'id': 'task', 'status': 'pending', 'assignees': ['manager']}]}
        WorkflowRun.objects.create(id='old-run', workflow_id='sales', workflow_version=4, form_id='form',
                                   submission_id='submission', status='pending', result_json=json.dumps(run))
        status, impact = self.call('workflow-personnel', data={'userId': 'former'})
        self.assertEqual(status, 200)
        flow = impact['flows'][0]
        self.assertEqual(flow['name'], '销售合同审批')
        self.assertEqual([node['type'] for node in flow['nodes']], ['start', 'condition', 'executor', 'cc', 'end'])
        self.assertEqual(flow['nodes'][1]['branches'][0]['nodes'][0]['assignees'], ['former'])

        request = {'workflowId': 'sales', 'nodeId': 'execute', 'updatedAt': flow['updatedAt'],
                   'source': 'manager', 'target': 'replacement', 'assignees': ['manager', 'admin']}
        endpoint = 'workflow-personnel/assignees'
        self.assertEqual(self.call(endpoint, 'post', request, user='manager')[0], 403)
        self.assertEqual(self.call(endpoint, 'post', {**request, 'assignees': ['manager']})[0], 409)
        self.assertEqual(self.call(endpoint, 'post', {**request, 'target': 'admin'})[0], 422)
        status, result = self.call(endpoint, 'post', request)
        self.assertEqual(status, 200)
        self.assertEqual(result['flow']['publishedVersion'], 5)
        self.assertEqual(result['flow']['nodes'][2]['assignees'], ['replacement', 'admin'])
        self.assertEqual(result['workflow']['publishedSnapshot']['name'], '销售合同审批')
        self.assertEqual(result['workflow']['name'], '尚未发布的名称修改')
        self.assertEqual(result['workflow']['draftSavedAt'], schema['draftSavedAt'])
        self.assertEqual(result['workflow']['nodes'][2]['assignees'], ['replacement', 'admin'])
        self.assertEqual(json.loads(WorkflowRun.objects.get(pk='old-run').result_json), run)
        self.assertEqual(self.call(endpoint, 'post', request)[0], 409)

    def test_first_editor_save_creates_one_linked_draft_and_can_be_retried(self):
        _, category = self.save_category()
        token = 'f' * 32
        form_id, workflow_id = 'form-' + token, 'flow-' + token
        resource = 'approval-drafts/' + workflow_id
        draft = {
            'form': {'id': form_id, 'name': '新申请', 'fields': []},
            'workflow': {'id': workflow_id, 'name': '新申请', 'category': category['key'], 'nodes': [
                {'id': 'start', 'type': 'start', 'name': '发起', 'formId': form_id},
                {'id': 'end', 'type': 'end', 'name': '结束'},
            ]},
        }
        self.assertEqual(self.call(resource, 'put', draft, user='replacement')[0], 403)
        self.assertEqual(Workflow.objects.count(), 0)
        status, result = self.call(resource, 'put', draft, user='manager')
        self.assertEqual(status, 201)
        self.assertTrue(result['workflow']['draftSavedAt'])
        self.assertIsNone(result['workflow']['publishedSnapshot'])
        self.assertEqual(result['workflow']['nodes'][0]['formId'], result['form']['id'])
        self.assertEqual(self.call(resource, 'put', draft, user='manager'), (200, result))
        self.assertEqual(Workflow.objects.count(), 1)
        draft['form']['name'] = '尝试覆盖'
        self.assertEqual(self.call(resource, 'put', draft, user='manager')[0], 409)
