import base64
import html
import io
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image
from django.test import TestCase, SimpleTestCase, override_settings

from identity_api.dingtalk.messages import send_markdown
from identity_api.models import RobotMessageBatch, RobotMessageImage
from identity_api.org.organization_access import OrganizationAccessError
from identity_api.robot_messages import deliver_batch
from identity_api.robot_rich_text import prepare_message, public_origin
from . import test_robot_messages as existing

BASE = existing.BASE


def raster(size=(4, 3)):
    output = io.BytesIO()
    Image.new('RGB', size, (33, 110, 210)).save(output, format='PNG')
    return output.getvalue()


PNG = raster()
SOURCE = 'data:image/png;base64,' + base64.b64encode(PNG).decode()
HTML = f'<p>会议通知<br><strong>下午三点</strong></p><p><img src="{SOURCE}"></p><p>请准时参加。</p>'


class RichMessageTests(TestCase):
    authenticate = existing.RobotMessageTests.authenticate
    grant = existing.RobotMessageTests.grant
    submit = existing.RobotMessageTests.submit

    def setUp(self):
        existing.RobotMessageTests.setUp(self)
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.media = Path(media.name)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        origin = patch.dict(os.environ, {'DINGTALK_JSAPI_ALLOWED_ORIGINS': 'https://messages.example.test', 'DINGTALK_ROBOT_IMAGE_ORIGIN': ''})
        origin.start()
        self.addCleanup(origin.stop)

    def test_mixed_content_is_sanitized_persisted_and_delivered_once_per_target(self):
        rid = str(uuid.uuid4())
        with patch('identity_api.robot_messages.enqueue_batch') as enqueue, self.captureOnCommitCallbacks(execute=True):
            first = self.submit(requestId=rid, contentHtml=HTML)
            repeat = self.submit(requestId=rid, contentHtml=HTML)
        self.assertEqual(first.status_code, 202, first.content)
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(first.json(), repeat.json())
        enqueue.assert_called_once()
        batch = RobotMessageBatch.objects.get()
        self.assertEqual(batch.message_key, 'sampleMarkdown')
        self.assertEqual(RobotMessageImage.objects.count(), 1)
        self.assertEqual(len(list(self.media.rglob('*.png'))), 1)
        self.assertIn('[图片]', batch.content)
        self.assertNotIn('base64', batch.content_html)
        self.assertIn('会议通知\n\n**下午三点**', batch.message_param['text'])
        self.assertIn('https://messages.example.test' + first.json()['images'][0]['url'], batch.message_param['text'])
        self.assertEqual(self.submit(requestId=rid, contentHtml=HTML + '改动').status_code, 409)
        self.assertEqual(self.submit(requestId=rid).status_code, 409)
        with patch('identity_api.robot_messages.send_markdown', return_value={'status': 'accepted'}) as outbound, patch('identity_api.robot_messages.send_text') as legacy:
            deliver_batch(batch.id)
            deliver_batch(batch.id)
        self.assertEqual(outbound.call_count, 2)
        self.assertEqual({call.args[1] for call in outbound.call_args_list}, {'person', 'group'})
        self.assertEqual(outbound.call_args.args[3], batch.message_param)
        legacy.assert_not_called()
        history = self.client.get(BASE + '/history', {'content': '下午三点'}).json()
        self.assertEqual(history['items'][0]['contentHtml'], batch.content_html)
        self.grant()
        self.authenticate(self.member)
        self.assertEqual(self.client.get(BASE + '/history').json()['total'], 0)
        self.assertEqual(self.client.get(BASE + '/requests/' + rid).status_code, 404)

    def test_image_only_and_text_only_use_one_message_format(self):
        for html, title in [(f'<img src="{SOURCE}">', '图片消息'), ('<p>纯文字</p>', '纯文字')]:
            response = self.submit(contentHtml=html)
            self.assertEqual(response.status_code, 202, response.content)
            batch = RobotMessageBatch.objects.get(request_id=response.json()['requestId'])
            self.assertEqual(batch.message_key, 'sampleMarkdown')
            self.assertEqual(batch.message_param['title'], title)

    def test_manual_web_links_are_persisted_as_in_client_links_and_reused_on_repeat(self):
        request_id = str(uuid.uuid4())
        body = '<p>请查看 https://oa.example.test/orders/123?tab=detail&amp;from=robot#result</p>'
        with patch('identity_api.robot_messages.enqueue_batch') as enqueue, self.captureOnCommitCallbacks(execute=True):
            created = self.submit(requestId=request_id, contentHtml=body)
            repeated = self.submit(requestId=request_id, contentHtml=body)
        self.assertEqual(created.status_code, 202)
        self.assertEqual(repeated.status_code, 200)
        enqueue.assert_called_once()
        batch = RobotMessageBatch.objects.get(request_id=request_id)
        self.assertIn('&target=fullScreen&targetDesktop=workbench', batch.message_param['text'])
        self.assertNotIn('applink.dingtalk.com', batch.content_html)
        with patch('identity_api.robot_messages.send_markdown', return_value={'status': 'accepted'}) as outbound:
            deliver_batch(batch.id)
        self.assertEqual(outbound.call_count, 2)
        self.assertEqual(outbound.call_args.args[3], batch.message_param)

    def test_public_image_requires_unguessable_token_and_returns_only_raster(self):
        response = self.submit(contentHtml=HTML)
        self.assertEqual(response.status_code, 202, response.content)
        image_url = response.json()['images'][0]['url']
        self.client.cookies.clear()
        public = self.client.get(image_url)
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public['Content-Type'], 'image/png')
        self.assertEqual(public['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(b''.join(public.streaming_content), PNG)
        public.close()
        head = self.client.head(image_url)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(int(head['Content-Length']), len(PNG))
        head.close()
        prefix, token = image_url.rsplit('/', 1)
        for invalid in ['x' * 43, '无效', token[:-1]]:
            self.assertEqual(self.client.get(prefix + '/' + invalid).status_code, 404)
        self.assertEqual(self.client.post(image_url, '{}', content_type='application/json').status_code, 405)
        stored = RobotMessageImage.objects.get()
        stored.file.delete(save=False)
        self.assertEqual(self.client.get(image_url).status_code, 404)

    def test_invalid_images_and_content_create_no_batch_or_files(self):
        invalid = [
            '<p><br></p>', '<script>alert(1)</script>',
            '<img src="https://example.test/tracker.png">',
            '<img src="data:image/svg+xml;base64,PHN2Zy8+">',
            '<img src="data:image/png;base64,aGVsbG8=">',
            f'<img src="{SOURCE.replace("image/png", "image/jpeg")}">',
            f'<img src="{SOURCE}">' * 7, '<p>' + '字' * 15000 + '</p>',
            '<div>' * 45 + '太深' + '</div>' * 45, '\ud800',
        ]
        for html in invalid:
            with self.subTest(html=html[:50]):
                self.assertEqual(self.submit(contentHtml=html).status_code, 400)
        with patch('identity_api.robot_rich_text.MAX_IMAGE_BYTES', len(PNG)):
            self.assertEqual(self.submit(contentHtml=f'<img src="{SOURCE}">' * 2).status_code, 400)
        with patch('identity_api.robot_rich_text.MAX_REQUEST_BYTES', 100):
            self.assertEqual(self.submit(contentHtml=HTML).status_code, 413)
        with patch.dict(os.environ, {'DINGTALK_JSAPI_ALLOWED_ORIGINS': 'http://insecure.test'}):
            self.assertEqual(self.submit(contentHtml=HTML).status_code, 400)
        self.assertEqual(RobotMessageBatch.objects.count(), 0)
        self.assertFalse(any(p.is_file() for p in self.media.rglob('*')))

    def test_transaction_failure_cleans_saved_files(self):
        with patch('identity_api.models.RobotMessageImage.save', side_effect=OrganizationAccessError('保存失败')):
            self.assertEqual(self.submit(contentHtml=HTML).status_code, 400)
        self.assertEqual(RobotMessageBatch.objects.count(), 0)
        self.assertEqual(RobotMessageImage.objects.count(), 0)
        self.assertFalse(any(p.is_file() for p in self.media.rglob('*')))

    def test_oversized_dimensions_are_rejected_before_storing(self):
        source = 'data:image/png;base64,' + base64.b64encode(raster((5000, 4001))).decode()
        self.assertEqual(self.submit(contentHtml=f'<img src="{source}">').status_code, 400)
        self.assertEqual(RobotMessageImage.objects.count(), 0)

    def test_large_request_bypasses_default_django_body_limit_safely(self):
        # A real valid raster padded with metadata-like trailing bytes stays under our 8 MB limit.
        source = 'data:image/png;base64,' + base64.b64encode(PNG + b'\0' * (3 * 1024 * 1024)).decode()
        response = self.submit(contentHtml=f'<img src="{source}">')
        self.assertEqual(response.status_code, 202, response.content[:200])
        self.assertEqual(RobotMessageImage.objects.count(), 1)

    def test_rich_writes_still_require_permission_and_same_origin(self):
        self.authenticate(self.member)
        self.assertEqual(self.submit(contentHtml=HTML).status_code, 403)
        self.grant()
        response = self.client.post(BASE + '/send', json.dumps({'requestId': str(uuid.uuid4()), 'contentHtml': HTML, 'groupIds': [self.group.id]}), content_type='application/json', HTTP_SEC_FETCH_SITE='cross-site')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(RobotMessageImage.objects.count(), 0)


class RichConversionTests(SimpleTestCase):
    def test_explicit_public_entry_point_takes_precedence_and_requires_https(self):
        with patch.dict(os.environ, {'DINGTALK_ROBOT_IMAGE_ORIGIN': 'https://messages.example.test:4433', 'DINGTALK_JSAPI_ALLOWED_ORIGINS': 'https://other.example.test'}):
            self.assertEqual(public_origin(), 'https://messages.example.test:4433')
            for origin in ['http://messages.example.test', 'https://[broken', 'https://example.test:bad', 'https://user:secret@example.test', 'https://example.test/path']:
                with patch.dict(os.environ, {'DINGTALK_ROBOT_IMAGE_ORIGIN': origin}):
                    with self.assertRaises(OrganizationAccessError):
                        public_origin()

    def test_sanitization_links_format_and_line_breaks(self):
        result = prepare_message('<p onclick="bad()">第一行<br>第二行 &amp; &lt;内容&gt;</p><script>bad()</script><a href="javascript:bad()">链接</a><a href="https://[bad">坏链接</a><a href="https://example.test/a(b)">有效链接</a>')
        self.assertNotIn('script', result['html'])
        self.assertNotIn('onclick', result['html'])
        self.assertNotIn('javascript', result['html'])
        self.assertIn('第一行\n\n第二行', result['params']['text'])
        self.assertIn('[有效链接](https://applink.dingtalk.com/page/link?url=https%3A%2F%2Fexample.test%2Fa%28b%29&target=fullScreen&targetDesktop=workbench)', result['params']['text'])
        self.assertIn('&lt;内容&gt;', result['html'])

    def web_destinations(self, result):
        links = re.findall(r'\((https://applink\.dingtalk\.com/page/link\?[^\s)]+)\)', result['params']['text'])
        destinations = []
        for link in links:
            parsed = urlsplit(link)
            self.assertEqual((parsed.netloc, parsed.path), ('applink.dingtalk.com', '/page/link'))
            query = parse_qs(parsed.query)
            self.assertEqual(query['target'], ['fullScreen'])
            self.assertEqual(query['targetDesktop'], ['workbench'])
            destinations.append(query['url'][0])
        return destinations

    def test_anchor_url_roundtrips_query_percent_port_fragment_and_chinese(self):
        url = 'https://oa.example.test:4433/订单/a(b)?next=%2Fcrm%3Fid%3D1&name=张三&plus=a+b#明细'
        result = prepare_message(f'<a href="{html.escape(url, quote=True)}"><strong>查看详情</strong></a>')
        self.assertEqual(self.web_destinations(result), [url])
        self.assertIn(html.escape(url, quote=True), result['html'])
        self.assertNotIn('applink.dingtalk.com', result['html'])

    def test_pasted_urls_preserve_order_and_exclude_sentence_delimiters(self):
        result = prepare_message('<p>访问https://example.test/a(b)?x=1&amp;y=2#tab。另见（http://example.test:8080/path），以及 https://example.test/end.</p>')
        self.assertEqual(self.web_destinations(result), ['https://example.test/a(b)?x=1&y=2#tab', 'http://example.test:8080/path', 'https://example.test/end'])
        self.assertIn('&target=fullScreen&targetDesktop=workbench)。另见（', result['params']['text'])
        result = prepare_message('<p>(https://example.test/wiki/A_(B))</p>')
        self.assertEqual(self.web_destinations(result), ['https://example.test/wiki/A_(B)'])

    def test_link_labels_code_images_and_non_web_actions_are_not_wrapped_twice(self):
        with patch.dict(os.environ, {'DINGTALK_ROBOT_IMAGE_ORIGIN': 'https://images.example.test'}):
            result = prepare_message('<a href="https://example.test/destination">https://example.test/label</a>'
                                     '<pre>https://example.test/code</pre><code>https://example.test/inline</code>'
                                     '<a href="mailto:a@example.test">邮件</a><a href="tel:123">电话</a>' + f'<img src="{SOURCE}">')
        self.assertEqual(self.web_destinations(result), ['https://example.test/destination'])
        self.assertIn('![](https://images.example.test/', result['params']['text'])
        self.assertIn('[邮件](mailto:a@example.test)', result['params']['text'])
        self.assertIn('[电话](tel:123)', result['params']['text'])

    def test_invalid_and_non_web_text_does_not_become_dingtalk_links(self):
        result = prepare_message('<p>https://[bad http://:80 https://example.test:bad ftp://example.test/data javascript:alert(1)</p>')
        self.assertEqual(self.web_destinations(result), [])

    def test_existing_applink_page_is_normalized_without_nesting_and_native_actions_survive(self):
        page = 'https://applink.dingtalk.com/page/link?url=https%3A%2F%2Fexample.test%2Forders%3Fid%3D1&targetDesktop=popupWindow'
        result = prepare_message(f'<a href="{html.escape(page, quote=True)}">订单</a><a href="https://applink.dingtalk.com/page/profile?uid=123&amp;name=a(b)">联系人</a>')
        self.assertEqual(self.web_destinations(result), ['https://example.test/orders?id=1'])
        self.assertIn('[联系人](https://applink.dingtalk.com/page/profile?uid=123&name=a%28b%29)', result['params']['text'])
        self.assertNotIn('targetDesktop=popupWindow', result['params']['text'])

    def test_size_limit_applies_after_web_link_encoding(self):
        with self.assertRaises(OrganizationAccessError):
            prepare_message('<a href="https://example.test/' + '中文' * 1000 + '">详情</a>')

    @patch('identity_api.dingtalk.messages._get_app_access_token', return_value='fake-secret')
    @patch('identity_api.dingtalk.messages.requests.post')
    def test_markdown_wire_format_uses_group_and_private_endpoints(self, post, token):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {'processQueryKey': 'receipt'}
        params = {'title': '通知', 'text': '通知\n\n![](https://example.test/image.png)'}
        for kind, target, endpoint in [('group', 'cid-test', 'groupMessages/send'), ('person', '00123', 'oToMessages/batchSend')]:
            self.assertEqual(send_markdown('robot', kind, target, params)['status'], 'accepted')
            self.assertTrue(post.call_args.args[0].endswith(endpoint))
            payload = post.call_args.kwargs['json']
            self.assertEqual(payload['msgKey'], 'sampleMarkdown')
            self.assertEqual(json.loads(payload['msgParam']), params)
            self.assertEqual(payload.get('userIds', [target]), [target])
        self.assertEqual(post.call_count, 2)
