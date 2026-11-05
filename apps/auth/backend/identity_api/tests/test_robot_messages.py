import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import requests
from django.test import TestCase, SimpleTestCase
from django.utils import timezone

from identity_api.auth.session import create_auth_session_token
from identity_api.auth.tokens import AUTH_COOKIE_NAME
from identity_api.dingtalk.messages import send_text
from identity_api.models import (Department, DepartmentEmployee, Employee, OrganizationState,
    RobotMessageBatch, RobotMessageDelivery, RobotMessageGroup, RobotMessagePermissionState, PlatformDepartmentState)
from identity_api.robot_messages import deliver_batch, enqueue_batch, settle_stale_deliveries

BASE = '/api/org/robot-messages'


class RobotMessageTests(TestCase):
    def setUp(self):
        self.client.defaults['HTTP_SEC_FETCH_SITE'] = 'same-origin'
        self.admin = Employee.objects.create(user_id='admin', name='管理员')
        self.member = Employee.objects.create(user_id='01333608525827896521', name='张三')
        self.other = Employee.objects.create(user_id='other', name='李四')
        dept = Department.objects.create(dept_id=1, name='销售部')
        child = Department.objects.create(dept_id=2, name='渠道组', parent_dept_id=1)
        for employee in (self.admin, self.member, self.other):
            DepartmentEmployee.objects.create(department=child, employee=employee)
        PlatformDepartmentState.objects.update_or_create(pk=1, defaults={'configured': False})
        OrganizationState.objects.update_or_create(pk=1, defaults={'revision': 5})
        self.group = RobotMessageGroup.objects.create(robot_code='test-bot', conversation_id='cid-test', name='测试群')
        self.state = RobotMessagePermissionState.objects.create(rules=[])
        for target, value in [('identity_api.org.queries.FULL_ACCESS_USER_IDS', {'admin'}),
                              ('identity_api.robot_messages.robot_config', ('test-bot', True))]:
            mock = patch(target, return_value=value) if target.endswith('robot_config') else patch(target, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.authenticate(self.admin)

    def authenticate(self, employee, actor=None):
        self.client.cookies[AUTH_COOKIE_NAME] = create_auth_session_token(employee, actor_employee=actor)['token']

    def grant(self, rules=None):
        self.state.rules = rules if rules is not None else [{'scopeType': 'employee', 'targetId': self.member.user_id}]
        self.state.save()

    def submit(self, **changes):
        payload = {'requestId': str(uuid.uuid4()), 'content': '测试通知', 'groupIds': [self.group.id], 'userIds': [self.member.user_id]}
        payload.update(changes)
        return self.client.post(BASE + '/send', json.dumps(payload), content_type='application/json')

    def test_auth_permissions_and_cross_site_write(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get(BASE + '/history').status_code, 401)
        self.authenticate(self.member)
        self.assertFalse(self.client.get(BASE + '/capabilities').json()['canSend'])
        for path in ['/history', '/groups', '/people', '/permissions']:
            self.assertEqual(self.client.get(BASE + path).status_code, 403)
        self.assertEqual(self.submit().status_code, 403)
        self.grant()
        self.assertTrue(self.client.get(BASE + '/capabilities').json()['canSend'])
        self.assertEqual(self.client.get(BASE + '/permissions').status_code, 403)
        self.assertEqual(self.client.post(BASE + '/send', '{}', content_type='application/json', HTTP_SEC_FETCH_SITE='cross-site').status_code, 403)

    def test_department_subtree_exclusions_and_proxy_identity(self):
        self.grant([{'scopeType': 'departmentSub', 'targetId': '1'}, {'scopeType': 'excludedEmployee', 'targetId': self.member.user_id}])
        self.authenticate(self.member, self.admin)
        self.assertFalse(self.client.get(BASE + '/capabilities').json()['canSend'])
        self.assertEqual(self.submit().status_code, 403)
        self.grant([{'scopeType': 'departmentSub', 'targetId': '1'}])
        self.assertEqual(self.submit().status_code, 202)
        batch = RobotMessageBatch.objects.get()
        self.assertEqual(batch.effective_user_id, self.member.user_id)
        self.assertEqual(batch.actor_user_id, self.admin.user_id)
        self.assertFalse(self.client.get(BASE + '/capabilities').json()['canManage'])

    def test_permission_revisions(self):
        payload = {'rules': [{'scopeType': 'employee', 'targetId': self.member.user_id}], 'revision': 1, 'orgRevision': 4}
        response = self.client.put(BASE + '/permissions', json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 409)
        payload['orgRevision'] = 5
        response = self.client.put(BASE + '/permissions', json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['effectiveMembers'][0]['userId'], self.member.user_id)
        self.assertEqual(self.client.put(BASE + '/permissions', json.dumps(payload), content_type='application/json').status_code, 409)

    def test_idempotency_validation_and_recipient_snapshots(self):
        rid = str(uuid.uuid4())
        with patch('identity_api.robot_messages.enqueue_batch') as enqueue, self.captureOnCommitCallbacks(execute=True):
            first = self.submit(requestId=rid)
            again = self.submit(requestId=rid)
        self.assertEqual(first.status_code, 202, first.content)
        self.assertEqual(again.status_code, 200)
        enqueue.assert_called_once()
        self.assertEqual(RobotMessageBatch.objects.count(), 1)
        self.assertEqual(RobotMessageDelivery.objects.count(), 2)
        self.assertEqual(RobotMessageDelivery.objects.get(kind='person').target_id, self.member.user_id)
        self.assertEqual(self.submit(requestId=rid, content='不同消息').status_code, 409)
        for changes in [{'userIds': [123]}, {'groupIds': [], 'userIds': []}, {'groupIds': [999999]}, {'content': '字' * 15000}, {'content': 'x\x00'}, {'content': '\ud800'}, {'groupIds': [2 ** 100]}]:
            self.assertEqual(self.submit(**changes).status_code, 400)
        self.member.account_status = Employee.ACCOUNT_DISABLED
        self.member.save()
        self.assertEqual(self.submit().status_code, 400)
        self.assertEqual(self.client.get(BASE + '/history', {'groupId': '9' * 100}).status_code, 400)

    def test_queue_failure_stops_late_task(self):
        self.submit()
        batch = RobotMessageBatch.objects.get()
        with patch('identity_api.tasks.send_robot_messages_task.apply_async', side_effect=RuntimeError('broker secret')):
            enqueue_batch(batch.id)
        with patch('identity_api.robot_messages.send_text') as outbound:
            deliver_batch(batch.id)
        outbound.assert_not_called()
        self.assertEqual(set(batch.deliveries.values_list('status', flat=True)), {'failed'})

    def test_notifications_use_their_own_queue_independent_of_directory_sync(self):
        from identity_api.tasks import send_robot_messages_task, sync_organization_contacts_task
        from mj_backend.celery import app
        self.submit()
        batch = RobotMessageBatch.objects.get()
        # Exercise the real Celery routing, intercepting only the broker publish.
        with patch.object(app.amqp, 'send_task_message') as publish:
            enqueue_batch(batch.id)
        publish.assert_called_once()
        self.assertEqual(publish.call_args.kwargs['queue'].name, 'auth_robot_messages')
        self.assertEqual(publish.call_args.args[1], send_robot_messages_task.name)
        sync_route = app.amqp.router.route({}, sync_organization_contacts_task.name)
        self.assertEqual(sync_route['queue'].name, 'auth_sync')

    def test_dispatch_partial_results_and_duplicate_worker(self):
        self.submit()
        batch = RobotMessageBatch.objects.get()
        with patch('identity_api.robot_messages.send_text', side_effect=[
            {'status': 'accepted', 'process_query_key': 'receipt'},
            {'status': 'unknown', 'message': '超时'},
        ]) as outbound:
            deliver_batch(batch.id)
            deliver_batch(batch.id)
        self.assertEqual(outbound.call_count, 2)
        self.assertEqual(self.client.get(BASE + '/history').json()['items'][0]['status'], 'unknown')
        self.assertEqual(self.client.get(BASE + '/groups').json()['items'][0]['sentCount'], 1)
        self.assertEqual(outbound.call_args.args[2], self.member.user_id)

    def test_revoked_permission_and_account_are_checked_by_worker(self):
        self.grant()
        self.authenticate(self.member)
        self.submit()
        self.grant([])
        with patch('identity_api.robot_messages.send_text') as outbound:
            deliver_batch(RobotMessageBatch.objects.get().id)
        outbound.assert_not_called()
        self.assertEqual(set(RobotMessageDelivery.objects.values_list('status', flat=True)), {'failed'})

    def test_history_is_private_and_unknown_attempts_never_retried(self):
        self.submit()
        batch = RobotMessageBatch.objects.get()
        RobotMessageDelivery.objects.filter(batch=batch).update(status='sending', started_at=timezone.now() - timedelta(minutes=4))
        self.grant()
        self.authenticate(self.member)
        self.assertEqual(self.client.get(BASE + '/history').json()['total'], 0)
        self.assertEqual(self.client.get(BASE + '/requests/' + str(batch.request_id)).status_code, 404)
        self.authenticate(self.admin)
        self.assertEqual(self.client.get(BASE + '/history').json()['items'][0]['status'], 'unknown')
        with patch('identity_api.robot_messages.send_text') as outbound:
            deliver_batch(batch.id)
        outbound.assert_not_called()

    def test_column_filters_apply_before_pagination_and_preserve_visibility(self):
        for index in range(22):
            response = self.submit(content=f'渠道通知 {index}')
            self.assertEqual(response.status_code, 202)
        RobotMessageDelivery.objects.update(status='accepted')
        RobotMessageBatch.objects.update(created_at=timezone.make_aware(datetime(2026, 10, 19, 0, 30)))
        # Sender/content are independent, and dates use the same Shanghai day as the UI.
        self.grant()
        self.authenticate(self.member)
        own = self.submit(content='管理员的通知').json()['requestId']
        self.authenticate(self.admin)
        params = {'sender': '管理员', 'target': '张三', 'content': '渠道通知', 'sentDate': '2026-10-19', 'status': 'accepted'}
        data = self.client.get(BASE + '/history', params).json()
        self.assertEqual(data['total'], 22)
        self.assertEqual(len(data['items']), 20)
        self.assertEqual(len(self.client.get(BASE + '/history', {**params, 'page': 2}).json()['items']), 2)
        for change in [{'sender': '张三'}, {'target': '不存在'}, {'content': '管理员'}, {'sentDate': '2026-10-18'}]:
            self.assertEqual(self.client.get(BASE + '/history', {**params, **change}).json()['total'], 0)
        self.authenticate(self.member)
        self.assertEqual(self.client.get(BASE + '/history', params).json()['total'], 0)
        own_records = self.client.get(BASE + '/history', {'sender': '张三', 'content': '管理员'}).json()
        self.assertEqual([r['requestId'] for r in own_records['items']], [own])
        for invalid in [{'sentDate': '2026-02-31'}, {'sentDate': 'yesterday'}, {'status': 'invalid'}]:
            self.assertEqual(self.client.get(BASE + '/history', invalid).status_code, 400)

    def test_status_filter_uses_all_recipients_and_settles_expired_attempts(self):
        expected = {'accepted': [], 'partial': [], 'unknown': [], 'sending': [], 'failed': []}
        scenarios = [(['accepted', 'accepted'], 'accepted'), (['accepted', 'failed'], 'partial'),
                     (['accepted', 'unknown'], 'unknown'), (['unknown', 'pending'], 'sending'),
                     (['failed', 'failed'], 'failed'), (['sending', 'accepted'], 'unknown'),
                     (['pending', 'failed'], 'failed')]
        for index, (states, final) in enumerate(scenarios):
            data = self.submit(content=f'状态测试 {index}').json()
            batch = RobotMessageBatch.objects.get(request_id=data['requestId'])
            for delivery, state in zip(batch.deliveries.order_by('id'), states):
                delivery.status = state
                if index == 5:
                    delivery.started_at = timezone.now() - timedelta(minutes=4)
                delivery.save()
            if index == 6:
                RobotMessageBatch.objects.filter(pk=batch.pk).update(created_at=timezone.now() - timedelta(hours=2))
            expected[final].append(data['requestId'])
        for status, ids in expected.items():
            data = self.client.get(BASE + '/history', {'status': status, 'target': self.group.name, 'groupId': self.group.id}).json()
            self.assertEqual(data['total'], len(ids))
            self.assertCountEqual([r['requestId'] for r in data['items']], ids)
            self.assertTrue(all(r['status'] == status for r in data['items']))

    def test_old_pending_tasks_expire_and_group_registration(self):
        response = self.client.post(BASE + '/groups', json.dumps({'name': '新群', 'openConversationId': 'cid-new'}), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.post(BASE + '/groups', json.dumps({'name': '新群', 'openConversationId': 'cid-new'}), content_type='application/json').status_code, 409)
        self.submit()
        batch = RobotMessageBatch.objects.get()
        RobotMessageBatch.objects.filter(pk=batch.pk).update(created_at=timezone.now() - timedelta(hours=2))
        settle_stale_deliveries([batch.pk])
        self.assertEqual(set(batch.deliveries.values_list('error_code', flat=True)), {'queue_expired'})


class DingTalkMessageTests(SimpleTestCase):
    @patch('identity_api.dingtalk.messages._get_app_access_token', return_value='fake-secret')
    @patch('identity_api.dingtalk.messages.requests.post')
    def test_wire_format_and_private_partial_rejection(self, post, token):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {'processQueryKey': 'receipt', 'invalidStaffIdList': [], 'flowControlledStaffIdList': []}
        result = send_text('robot', 'person', '00123', '通知')
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(post.call_args.kwargs['json']['userIds'], ['00123'])
        self.assertEqual(json.loads(post.call_args.kwargs['json']['msgParam']), {'content': '通知'})
        for key in ('invalidStaffIdList', 'flowControlledStaffIdList'):
            post.return_value.json.return_value = {'processQueryKey': 'receipt', key: ['00123']}
            self.assertEqual(send_text('robot', 'person', '00123', '通知')['status'], 'failed')
        post.return_value.json.return_value = {'processQueryKey': 'receipt'}
        send_text('robot', 'group', 'cid-test', '通知')
        self.assertEqual(post.call_args.kwargs['json']['openConversationId'], 'cid-test')

    @patch('identity_api.dingtalk.messages._get_app_access_token', return_value='fake-secret')
    @patch('identity_api.dingtalk.messages.requests.post', side_effect=requests.Timeout('fake-secret'))
    def test_timeout_is_uncertain_without_retry_or_secrets(self, post, token):
        result = send_text('robot', 'group', 'cid-test', '消息')
        self.assertEqual(result['status'], 'unknown')
        self.assertNotIn('fake-secret', json.dumps(result))
        post.assert_called_once()
