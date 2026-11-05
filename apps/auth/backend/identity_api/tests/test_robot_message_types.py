import base64
import copy
import json
import uuid
from unittest.mock import Mock, patch

import requests
from django.test import TestCase

from identity_api.dingtalk.messages import send_markdown, send_text
from identity_api.models import InternalServiceCredential, RobotMessageBatch, RobotMessageImage, RobotMessageMedia
from identity_api.org.organization_access import OrganizationAccessError
from identity_api.robot_media import upload_to_dingtalk
from identity_api.robot_messages import deliver_batch
from . import test_robot_messages_internal as internal
from . import test_robot_rich_messages as rich


class TypedRobotMessageTests(TestCase):
    authenticate = internal.InternalRobotMessageTests.authenticate
    grant = internal.InternalRobotMessageTests.grant
    headers = internal.InternalRobotMessageTests.headers
    post = internal.InternalRobotMessageTests.post

    def setUp(self):
        internal.InternalRobotMessageTests.setUp(self)
        config = patch('identity_api.robot_media.robot_config', return_value=('test-bot', True))
        config.start()
        self.addCleanup(config.stop)
        self.assets = {}
        for kind, name in [('file', '订单.pdf'), ('image', '封面.png'), ('audio', '提醒.amr'), ('video', '说明.mp4')]:
            self.assets[kind] = RobotMessageMedia.objects.create(source_app_id='crm', source_service='crm-backend',
                robot_code='test-bot', kind=kind, upstream_media_id='upstream-' + kind, file_name=name, byte_size=100)

    def send_typed(self, message, **changes):
        payload = {'messageRequestId': str(uuid.uuid4()), 'message': message,
                   'groupIds': [self.group.id], 'userIds': [self.member.user_id]}
        payload.update(changes)
        return self.post('/send', payload)

    def cases(self):
        yield {'type': 'text', 'text': '原样 **文本**'}, 'sampleText', {'content': '原样 **文本**'}
        yield {'type': 'markdown', 'title': '通知', 'text': '**正文**'}, 'sampleMarkdown', {'title': '通知', 'text': '**正文**'}
        yield {'type': 'image', 'url': 'https://example.test/photo.png'}, 'sampleImageMsg', {'photoURL': 'https://example.test/photo.png'}
        target = 'https://example.test/orders/1?a=2#detail'
        link = 'https://applink.dingtalk.com/page/link?url=https%3A%2F%2Fexample.test%2Forders%2F1%3Fa%3D2%23detail&target=fullScreen&targetDesktop=workbench'
        yield {'type': 'link', 'title': '订单', 'text': '说明', 'url': target, 'imageMediaId': str(self.assets['image'].id)}, 'sampleLink', {'title': '订单', 'text': '说明', 'messageUrl': link, 'picUrl': 'upstream-image'}
        for size, layout in [(1, 'vertical'), (2, 'vertical'), (3, 'vertical'), (4, 'vertical'), (5, 'vertical'), (2, 'horizontal')]:
            spec = {'type': 'actionCard', 'title': '订单', 'text': '**说明**', 'layout': layout,
                    'buttons': [{'title': '查看' + str(i), 'url': target} for i in range(1, size + 1)]}
            params = {'title': '订单', 'text': '**说明**'}
            key = 'sampleActionCard'
            if size == 1:
                params.update(singleTitle='查看1', singleURL=link)
            else:
                key += str(6 if layout == 'horizontal' else size)
                for i in range(1, size + 1):
                    params.update({f'buttonTitle{i}' if layout == 'horizontal' else f'actionTitle{i}': '查看' + str(i),
                                   f'buttonUrl{i}' if layout == 'horizontal' else f'actionURL{i}': link})
            yield spec, key, params
        yield {'type': 'file', 'mediaId': str(self.assets['file'].id)}, 'sampleFile', {'mediaId': 'upstream-file', 'fileName': '订单.pdf', 'fileType': 'pdf'}
        yield {'type': 'audio', 'mediaId': str(self.assets['audio'].id), 'durationMs': 3500}, 'sampleAudio', {'mediaId': 'upstream-audio', 'duration': '3500'}
        yield {'type': 'video', 'mediaId': str(self.assets['video'].id), 'coverMediaId': str(self.assets['image'].id), 'durationSeconds': 30, 'width': 1920, 'height': 1080}, 'sampleVideo', {'videoMediaId': 'upstream-video', 'picMediaId': 'upstream-image', 'videoType': 'mp4', 'duration': '30', 'width': '1920', 'height': '1080'}

    def test_all_13_templates_send_correct_wire_parameters_to_both_recipient_kinds_once(self):
        response = Mock(status_code=200)
        response.json.return_value = {'processQueryKey': 'mock-receipt'}
        with patch('identity_api.robot_messages.send_markdown', side_effect=send_markdown), patch('identity_api.robot_messages.send_text', side_effect=send_text), patch('identity_api.dingtalk.messages._get_app_access_token', return_value='not-real'), patch('identity_api.dingtalk.messages.requests.post', return_value=response) as outbound:
            for spec, key, params in self.cases():
                with self.subTest(key=key):
                    created = self.send_typed(spec)
                    self.assertEqual(created.status_code, 202, created.content)
                    batch = RobotMessageBatch.objects.get(id=created.json()['id'])
                    self.assertEqual(batch.message_key, key)
                    self.assertEqual(batch.message_param, params)
                    before = outbound.call_count
                    deliver_batch(batch.id)
                    deliver_batch(batch.id)
                    self.assertEqual(outbound.call_count - before, 2)
                    for call in outbound.call_args_list[-2:]:
                        body = call.kwargs['json']
                        self.assertEqual((body['msgKey'], json.loads(body['msgParam'])), (key, params))
                        self.assertFalse(call.kwargs['allow_redirects'])
                    self.assertEqual(outbound.call_args_list[-2].kwargs['json']['openConversationId'], 'cid-test')
                    self.assertEqual(outbound.call_args_list[-1].kwargs['json']['userIds'], [self.member.user_id])
                    result = self.post('/requests/get', {'messageRequestId': str(batch.request_id)}).json()
                    self.assertEqual(result['status'], 'accepted')
                    self.assertEqual(result['message']['type'], spec['type'])
                    self.assertNotIn('upstream-', json.dumps(result))

    def test_canonical_idempotency_and_type_body_button_media_conflicts(self):
        for original, _, _ in self.cases():
            rid = str(uuid.uuid4())
            with patch('identity_api.robot_messages.enqueue_batch') as enqueue, self.captureOnCommitCallbacks(execute=True):
                first = self.send_typed(original, messageRequestId=rid)
                again = self.send_typed(dict(reversed(list(original.items()))), messageRequestId=rid)
            self.assertEqual(first.status_code, 202)
            self.assertEqual(again.status_code, 200)
            enqueue.assert_called_once()
            altered = copy.deepcopy(original)
            if altered['type'] == 'actionCard':
                altered['buttons'][0]['title'] += '改'
            elif 'mediaId' in altered:
                altered['mediaId'] = str(uuid.uuid4())
            elif 'text' in altered:
                altered['text'] += '改'
            else:
                altered['url'] += '?changed=1'
            self.assertEqual(self.send_typed(altered, messageRequestId=rid).status_code, 409)
            self.assertEqual(self.send_typed({'type': 'text', 'text': '不同类型'}, messageRequestId=rid).status_code, 409)
            self.assertEqual(self.post('/send', {'messageRequestId': rid, 'content': '旧格式', 'userIds': [self.member.user_id]}).status_code, 409)

    def test_rich_typed_and_image_data_uris_store_once_and_return_no_base64(self):
        for spec in [{'type': 'image', 'url': rich.SOURCE}, {'type': 'markdown', 'title': '图文', 'contentHtml': rich.HTML},
                     {'type': 'actionCard', 'title': '图文', 'contentHtml': rich.HTML, 'buttons': [{'title': '详情', 'url': 'https://example.test'}]}]:
            rid = str(uuid.uuid4())
            first = self.send_typed(spec, messageRequestId=rid)
            repeated = self.send_typed(spec, messageRequestId=rid)
            self.assertEqual((first.status_code, repeated.status_code), (202, 200), first.content)
            self.assertNotIn('base64', first.content.decode())
            batch = RobotMessageBatch.objects.get(request_id=rid)
            self.assertEqual(batch.images.count(), 1)
        self.assertEqual(RobotMessageImage.objects.count(), 3)
        self.assertEqual(len(list(self.media.rglob('*.png'))), 3)

    def test_raw_markdown_is_preserved_and_history_is_escaped(self):
        body = '<script>alert(1)</script>\n[详情](https://example.test)'
        response = self.send_typed({'type': 'markdown', 'title': '<img src=x onerror=x>', 'text': body})
        self.assertEqual(response.status_code, 202)
        batch = RobotMessageBatch.objects.get(id=response.json()['id'])
        self.assertEqual(batch.message_param['text'], body)
        self.assertNotIn('<script>', batch.content_html)
        self.assertNotIn('<img ', batch.content_html)
        linked = self.send_typed({'type': 'link', 'title': '链接', 'text': '说明', 'url': 'https://example.test', 'imageUrl': 'https://example.test/cover.png'})
        self.assertEqual(linked.status_code, 202)

    def test_invalid_schemas_and_exclusive_fields_create_nothing(self):
        invalid = [None, [], {}, {'type': []}, {'type': 'unsupported'}, {'type': 'text', 'text': '\ud800'},
                   {'type': 'text', 'text': 'ok', 'unknown': True}, {'type': 'text', 'text': '中' * 6000},
                   {'type': 'text', 'text': 'bad\x00'}, {'type': 'markdown', 'title': 'x', 'text': 'a', 'contentHtml': 'b'},
                   {'type': 'markdown', 'title': 'x', 'contentHtml': None}, {'type': 'image', 'url': 'javascript:alert(1)'},
                   {'type': 'image', 'url': 'http://example.test/a.png'}, {'type': 'image', 'url': 'data:image/svg+xml;base64,PHN2Zz4='},
                   {'type': 'link', 'title': 'x', 'text': 'x', 'url': 'https://a', 'imageUrl': 'https://b', 'imageMediaId': str(self.assets['image'].id)},
                   {'type': 'actionCard', 'title': 'x', 'text': 'x', 'buttons': []},
                   {'type': 'actionCard', 'title': 'x', 'text': 'x', 'layout': 'horizontal', 'buttons': [{'title': 'a', 'url': 'https://a'}]},
                   {'type': 'actionCard', 'title': 'x', 'text': 'x', 'buttons': [{'title': 'a', 'url': 'javascript:alert(1)'}]},
                   {'type': 'file', 'mediaId': 'raw-dingtalk-id'},
                   {'type': 'audio', 'mediaId': str(self.assets['audio'].id), 'durationMs': True},
                   {'type': 'audio', 'mediaId': str(self.assets['audio'].id), 'durationMs': 0},
                   {'type': 'video', 'mediaId': str(self.assets['video'].id), 'coverMediaId': str(self.assets['image'].id), 'durationSeconds': 3, 'width': 1}]
        for spec in invalid:
            with self.subTest(spec=str(spec)[:100]):
                self.assertEqual(self.send_typed(spec).status_code, 400)
        self.assertEqual(self.send_typed({'type': 'text', 'text': 'a'}, content='b').status_code, 400)
        self.assertEqual(self.send_typed({'type': 'text', 'text': 'a'}, contentHtml='b').status_code, 400)
        self.assertEqual(RobotMessageBatch.objects.count(), 0)

    def test_media_ownership_wrong_kind_and_changed_robot_are_enforced(self):
        asset = self.assets['file']
        for service in ('cable-mall-backend', 'crm-other'):
            self.assertEqual(self.post('/media/get', {'mediaId': str(asset.id)}, service=service).status_code, 404)
            response = self.post('/send', {'messageRequestId': str(uuid.uuid4()), 'message': {'type': 'file', 'mediaId': str(asset.id)}, 'userIds': [self.member.user_id]}, service=service)
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.send_typed({'type': 'file', 'mediaId': str(self.assets['image'].id)}).status_code, 400)
        with patch('identity_api.robot_media.robot_config', return_value=('changed', True)):
            self.assertEqual(self.post('/media/get', {'mediaId': str(asset.id)}).status_code, 404)
            self.assertEqual(self.send_typed({'type': 'file', 'mediaId': str(asset.id)}).status_code, 404)

    def test_worker_rechecks_media_owner_service_and_fails_closed_for_unknown_template(self):
        with patch('identity_api.robot_messages.send_message') as send:
            for alteration in ('media', 'service', 'template'):
                asset = self.assets['file']
                asset.source_service = 'crm-backend'; asset.save()
                InternalServiceCredential.objects.filter(service_name='crm-backend').update(enabled=True)
                response = self.send_typed({'type': 'file', 'mediaId': str(asset.id)})
                batch = RobotMessageBatch.objects.get(id=response.json()['id'])
                if alteration == 'media':
                    asset.source_service = 'crm-other'; asset.save()
                elif alteration == 'service':
                    InternalServiceCredential.objects.filter(service_name='crm-backend').update(enabled=False)
                else:
                    batch.message_key = 'unknown'; batch.save()
                deliver_batch(batch.id)
                self.assertEqual(set(batch.deliveries.values_list('status', flat=True)), {'failed'})
            send.assert_not_called()
            self.outbound.assert_not_called()

    def test_new_routes_authenticate_before_parsing_and_capabilities_match_supported_types(self):
        for endpoint in ('/media/upload', '/media/get', '/capabilities'):
            response = self.client.post(internal.BASE + endpoint, '{bad', content_type='application/json')
            self.assertEqual(response.status_code, 403)
        result = self.post('/capabilities', {}).json()
        self.assertEqual(set(result['messageTypes']), {'text', 'markdown', 'image', 'link', 'actionCard', 'file', 'audio', 'video'})
        self.assertEqual(result['media']['audio'], {'maxBytes': 2 * 1024 * 1024, 'extensions': ['amr']})
        self.assertEqual(result['actionCard']['horizontalButtons'], [2])

    def test_upload_success_stores_scoped_metadata_and_no_upstream_id_in_response(self):
        files = [('image', '封面.png', rich.PNG), ('file', '订单.pdf', b'%PDF-1.4\nmock'),
                 ('audio', '提醒.amr', b'#!AMR\nmock'), ('video', '说明.mp4', b'\x00\x00\x00\x18ftypmp42mock')]
        with patch('identity_api.robot_media.upload_to_dingtalk', return_value='upstream-secret-id') as upload:
            for kind, name, data in files:
                response = self.post('/media/upload', {'kind': kind, 'fileName': name, 'contentBase64': base64.b64encode(data).decode()})
                self.assertEqual(response.status_code, 201, response.content)
                self.assertNotIn('upstream-', response.content.decode())
                record = RobotMessageMedia.objects.get(pk=response.json()['id'])
                self.assertEqual((record.kind, record.byte_size, record.source_service), (kind, len(data), 'crm-backend'))
                lookup = self.post('/media/get', {'mediaId': str(record.id)})
                self.assertEqual(lookup.status_code, 200)
                self.assertEqual(lookup.json()['fileName'], name)
            self.assertEqual(upload.call_count, 4)

    def test_upload_validation_limits_and_revocation_do_not_store_material(self):
        original_count = RobotMessageMedia.objects.count()
        valid = {'kind': 'file', 'fileName': 'a.pdf', 'contentBase64': base64.b64encode(b'%PDF-test').decode()}
        for changes in [{'kind': 'other'}, {'fileName': '../a.pdf'}, {'fileName': 'a.exe'}, {'fileName': '\ud800.pdf'},
                        {'contentBase64': 'data:abc'}, {'contentBase64': ''}, {'contentBase64': 'a' * (28 * 1024 * 1024)},
                        {'kind': 'image', 'fileName': 'a.png'}, {'kind': 'audio', 'fileName': 'a.mp3'}]:
            with patch('identity_api.robot_media.upload_to_dingtalk') as upload:
                self.assertIn(self.post('/media/upload', {**valid, **changes}).status_code, (400, 413))
                upload.assert_not_called()
        with patch('identity_api.robot_media.MAX_UPLOAD_BODY', 20):
            self.assertEqual(self.post('/media/upload', valid).status_code, 413)
        def revoke(*args):
            InternalServiceCredential.objects.filter(service_name='crm-backend').update(enabled=False)
            return 'uploaded'
        with patch('identity_api.robot_media.upload_to_dingtalk', side_effect=revoke):
            self.assertEqual(self.post('/media/upload', valid).status_code, 403)
        self.assertEqual(RobotMessageMedia.objects.count(), original_count)

    def test_upload_transport_uses_multipart_voice_and_sanitizes_every_failure(self):
        response = Mock(status_code=200)
        response.json.return_value = {'errcode': 0, 'media_id': 'test-id'}
        with patch('identity_api.robot_media._get_app_access_token', return_value='sensitive-token'), patch('identity_api.robot_media.requests.post', return_value=response) as post:
            self.assertEqual(upload_to_dingtalk('audio', 'a.amr', b'#!AMR\n', 'audio/amr'), 'test-id')
            self.assertEqual(post.call_args.kwargs['data'], {'type': 'voice'})
            self.assertEqual(post.call_args.kwargs['files']['media'], ('a.amr', b'#!AMR\n', 'audio/amr'))
            self.assertFalse(post.call_args.kwargs['allow_redirects'])
            for status, payload in [(200, []), (200, {}), (200, {'errcode': 1, 'errmsg': 'sensitive-token'}), (302, {'errcode': 0, 'media_id': 'id'}), (500, {})]:
                response.status_code, response.json.return_value = status, payload
                before = post.call_count
                with self.assertRaises(OrganizationAccessError) as caught:
                    upload_to_dingtalk('file', 'a.pdf', b'%PDF-', 'application/pdf')
                self.assertEqual(post.call_count - before, 1)
                self.assertNotIn('sensitive', str(caught.exception))
            post.side_effect = requests.Timeout('sensitive-token')
            with self.assertRaises(OrganizationAccessError) as caught:
                upload_to_dingtalk('file', 'a.pdf', b'%PDF-', 'application/pdf')
            self.assertEqual(caught.exception.code, 'ROBOT_MEDIA_UPLOAD_FAILED')
            self.assertNotIn('sensitive', str(caught.exception))
