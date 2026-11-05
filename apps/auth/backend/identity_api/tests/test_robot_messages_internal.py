import json
import uuid
from unittest.mock import patch

from django.test import TestCase

from identity_api.models import InternalServiceCredential, RobotMessageBatch, RobotMessageDelivery, RobotMessageGroup, RobotMessageImage
from identity_api.robot_messages import deliver_batch, enqueue_batch
from . import test_robot_messages as manual
from . import test_robot_rich_messages as rich

BASE = '/api/internal/robot-messages'
SECRET = 'test-robot-service-credential-not-real-0123456789'


class InternalRobotMessageTests(TestCase):
    authenticate = manual.RobotMessageTests.authenticate
    grant = manual.RobotMessageTests.grant

    def setUp(self):
        rich.RichMessageTests.setUp(self)
        for app, service in [('crm', 'crm-backend'), ('cable-mall', 'cable-mall-backend'), ('crm', 'crm-other')]:
            credential = InternalServiceCredential(app_id=app, service_name=service)
            credential.set_secret(SECRET + service)
            credential.save()
        for target, value in [('identity_api.robot_messages_internal.application_name', '客户管理'),
                              ('identity_api.robot_messages_internal.robot_config', ('test-bot', True)),
                              ('identity_api.robot_messages.send_markdown', {'status': 'accepted'})]:
            mocked = patch(target, return_value=value)
            mock = mocked.start()
            self.addCleanup(mocked.stop)
            if target.endswith('send_markdown'):
                self.outbound = mock

    def headers(self, service='crm-backend'):
        return {'HTTP_X_INTERNAL_SERVICE': service, 'HTTP_X_INTERNAL_AUTH_SECRET': SECRET + service}

    def post(self, path, payload, service='crm-backend', **headers):
        return self.client.post(BASE + path, json.dumps(payload), content_type='application/json', **{**self.headers(service), **headers})

    def send(self, service='crm-backend', **changes):
        payload = {'messageRequestId': str(uuid.uuid4()), 'contentHtml': rich.HTML,
                   'groupIds': [self.group.id], 'userIds': [self.member.user_id], 'businessKey': 'order:123:approved'}
        payload.update(changes)
        return self.post('/send', payload, service=service)

    def test_every_endpoint_requires_its_registered_service_even_with_an_admin_cookie(self):
        for endpoint in ['/send', '/requests/get', '/groups/query']:
            for headers, code in [({}, 'MISSING_INTERNAL_SERVICE'), ({'HTTP_X_INTERNAL_SERVICE': 'unregistered-backend'}, 'UNKNOWN_INTERNAL_SERVICE'),
                                  ({'HTTP_X_INTERNAL_SERVICE': 'crm-backend'}, 'INVALID_INTERNAL_SECRET'),
                                  ({**self.headers(), 'HTTP_X_INTERNAL_SERVICE': 'cable-mall-backend'}, 'INVALID_INTERNAL_SECRET')]:
                response = self.client.post(BASE + endpoint, '{}', content_type='application/json', **headers)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()['code'], code)
        InternalServiceCredential.objects.filter(service_name='crm-backend').update(enabled=False)
        self.assertEqual(self.send().json()['code'], 'INTERNAL_SERVICE_DISABLED')
        self.assertEqual(RobotMessageBatch.objects.count(), 0)
        self.outbound.assert_not_called()

    def test_system_send_persists_app_identity_and_one_message_per_recipient(self):
        self.client.cookies.clear()
        with patch('identity_api.robot_messages.enqueue_batch') as enqueue, self.captureOnCommitCallbacks(execute=True):
            response = self.send()
        self.assertEqual(response.status_code, 202, response.content)
        enqueue.assert_called_once()
        data = response.json()
        self.assertEqual(data['requestId'], response['X-Request-Id'])
        self.assertNotEqual(data['messageRequestId'], data['requestId'])
        self.assertEqual((data['sourceAppId'], data['sourceService']), ('crm', 'crm-backend'))
        self.assertEqual(data['sourceKind'], 'application')
        self.assertEqual(data['senderName'], '客户管理')
        batch = RobotMessageBatch.objects.get()
        self.assertEqual((batch.effective_user_id, batch.actor_user_id), ('', ''))
        self.assertEqual(batch.business_key, 'order:123:approved')
        self.assertEqual(batch.message_key, 'sampleMarkdown')
        deliver_batch(batch.id)
        deliver_batch(batch.id)
        self.assertEqual(self.outbound.call_count, 2)
        self.assertEqual(self.outbound.call_args.args[2], self.member.user_id)
        self.assertTrue(self.outbound.call_args.args[2].startswith('0'))
        result = self.post('/requests/get', {'messageRequestId': data['messageRequestId']}).json()
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['recipients'][1]['userId'], self.member.user_id)
        self.assertNotIn(SECRET, json.dumps(result))

    def test_plain_text_is_escaped_into_the_same_markdown_format(self):
        response = self.post('/send', {'messageRequestId': str(uuid.uuid4()), 'content': '<重要>\n请查看订单', 'userIds': [self.member.user_id]})
        self.assertEqual(response.status_code, 202, response.content)
        batch = RobotMessageBatch.objects.get()
        self.assertEqual(batch.message_key, 'sampleMarkdown')
        self.assertIn('&lt;重要&gt;<br>', batch.content_html)
        self.assertIn('\n\n请查看订单', batch.message_param['text'])
        self.assertEqual(self.post('/send', {'messageRequestId': str(uuid.uuid4()), 'contentHtml': f'<img src="{rich.SOURCE}">', 'groupIds': [self.group.id]}).status_code, 202)

    def test_application_plain_and_rich_links_use_dingtalk_browser(self):
        for body in [{'content': '查看 https://oa.example.test/order?id=123&tab=items'},
                     {'contentHtml': '<p><a href="https://oa.example.test/order?id=123&amp;tab=items">查看订单</a></p>'}]:
            response = self.post('/send', {'messageRequestId': str(uuid.uuid4()), 'userIds': [self.member.user_id], **body})
            self.assertEqual(response.status_code, 202)
            batch = RobotMessageBatch.objects.get(request_id=response.json()['messageRequestId'])
            self.assertIn('https://applink.dingtalk.com/page/link?url=https%3A%2F%2Foa.example.test%2Forder%3Fid%3D123%26tab%3Ditems&target=fullScreen&targetDesktop=workbench', batch.message_param['text'])
            self.assertNotIn('applink.dingtalk.com', batch.content_html)

    def test_idempotency_compares_service_targets_content_and_business_key_without_duplicating_images(self):
        key = str(uuid.uuid4())
        with patch('identity_api.robot_messages.enqueue_batch') as enqueue, self.captureOnCommitCallbacks(execute=True):
            first = self.send(messageRequestId=key).json()
            same = self.send(messageRequestId=key)
        self.assertEqual(same.status_code, 200)
        self.assertEqual(same.json()['id'], first['id'])
        self.assertEqual(same.json()['images'], first['images'])
        enqueue.assert_called_once()
        for changes in [{'service': 'cable-mall-backend'}, {'service': 'crm-other'}, {'businessKey': 'other'}, {'contentHtml': '<p>改动</p>'}, {'userIds': []}]:
            response = self.send(messageRequestId=key, **changes)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()['code'], 'REQUEST_CONFLICT')
        self.assertEqual(RobotMessageBatch.objects.count(), 1)
        self.assertEqual(RobotMessageImage.objects.count(), 1)
        self.assertEqual(len(list(self.media.rglob('*.png'))), 1)

    def test_service_and_manual_history_are_isolated(self):
        data = self.send().json()
        for service in ['cable-mall-backend', 'crm-other']:
            response = self.post('/requests/get', {'messageRequestId': data['messageRequestId']}, service=service)
            self.assertEqual(response.status_code, 404)
        self.grant()
        self.authenticate(self.member)
        self.assertEqual(self.client.get(manual.BASE + '/history').json()['total'], 0)
        self.assertEqual(self.client.get(manual.BASE + '/requests/' + data['messageRequestId']).status_code, 404)
        human = manual.RobotMessageTests.submit(self).json()
        self.assertEqual(self.post('/requests/get', {'messageRequestId': human['requestId']}).status_code, 404)
        self.assertEqual(manual.RobotMessageTests.submit(self, requestId=data['messageRequestId'], contentHtml=rich.HTML).status_code, 409)
        self.authenticate(self.admin)
        self.assertEqual(self.client.get(manual.BASE + '/history', {'sender': '客户管理'}).json()['total'], 1)

    def test_untrusted_identity_fields_and_invalid_payloads_cannot_create_records(self):
        for changes in [{'sourceAppId': 'crm'}, {'actorUserId': 'admin'}, {'token': 'token'}, {'sourceService': 'crm-backend'},
                        {'content': '同时提供两种'}, {'contentHtml': None}, {'businessKey': 'x' * 201},
                        {'businessKey': 'x\x00'}, {'messageRequestId': 'bad'}, {'userIds': [123]}, {'groupIds': [999]}]:
            self.assertEqual(self.send(**changes).status_code, 400)
        response = self.client.post(BASE + '/send', '{bad', content_type='application/json', **self.headers())
        self.assertEqual(response.status_code, 400)
        with patch('identity_api.robot_rich_text.MAX_REQUEST_BYTES', 100):
            self.assertEqual(self.send().status_code, 413)
        self.assertEqual(RobotMessageBatch.objects.count(), 0)
        self.assertFalse(any(p.is_file() for p in self.media.rglob('*')))

    def test_revoked_or_reassigned_service_blocks_queued_deliveries(self):
        for change in [{'enabled': False}, {'app_id': 'other'}]:
            InternalServiceCredential.objects.filter(service_name='crm-backend').update(enabled=True, app_id='crm')
            data = self.send().json()
            InternalServiceCredential.objects.filter(service_name='crm-backend').update(**change)
            deliver_batch(data['id'])
            self.assertEqual(set(RobotMessageDelivery.objects.filter(batch_id=data['id']).values_list('status', flat=True)), {'failed'})
        self.outbound.assert_not_called()

    def test_disabled_recipient_is_rechecked_and_unknown_result_is_not_retried(self):
        data = self.send().json()
        self.member.account_status = self.member.ACCOUNT_DISABLED
        self.member.save()
        self.outbound.return_value = {'status': 'unknown', 'message': '超时'}
        deliver_batch(data['id'])
        deliver_batch(data['id'])
        self.outbound.assert_called_once()
        result = self.post('/requests/get', {'messageRequestId': data['messageRequestId']}).json()
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual([r['status'] for r in result['recipients']], ['unknown', 'failed'])

    def test_queue_failure_blocks_a_late_task(self):
        data = self.send().json()
        with patch('identity_api.tasks.send_robot_messages_task.apply_async', side_effect=RuntimeError('broker unavailable')):
            enqueue_batch(data['id'])
        deliver_batch(data['id'])
        self.outbound.assert_not_called()
        self.assertEqual(self.post('/requests/get', {'messageRequestId': data['messageRequestId']}).json()['status'], 'failed')

    def test_groups_query_is_paginated_and_only_returns_current_enabled_robot_groups(self):
        RobotMessageGroup.objects.create(robot_code='test-bot', conversation_id='cid-two', name='测试群二')
        RobotMessageGroup.objects.create(robot_code='other-bot', conversation_id='cid-other', name='其他群')
        RobotMessageGroup.objects.create(robot_code='test-bot', conversation_id='cid-disabled', name='停用群', enabled=False)
        first = self.post('/groups/query', {'keyword': '测试', 'limit': 1}).json()
        second = self.post('/groups/query', {'keyword': '测试', 'limit': 1, 'offset': 1}).json()
        self.assertEqual(first['total'], 2)
        self.assertEqual(len(first['items']), 1)
        self.assertNotEqual(first['items'], second['items'])
        self.assertEqual(first['maxTargets'], 100)
        self.assertEqual(first['maxImages'], 6)
        for payload in [{'offset': -1}, {'limit': 101}, {'limit': True}, {'keyword': '\x00'}]:
            self.assertEqual(self.post('/groups/query', payload).status_code, 400)
