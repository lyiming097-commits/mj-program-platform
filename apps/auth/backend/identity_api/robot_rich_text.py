"""Validate editor HTML and convert one composed message to DingTalk Markdown."""
import base64
import binascii
import hashlib
import html
import io
import json
import os
import re
import secrets
import uuid
import warnings
from html.parser import HTMLParser
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from PIL import Image, UnidentifiedImageError
from django.core.files.base import ContentFile

from .org.organization_access import OrganizationAccessError

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 6
MAX_REQUEST_BYTES = 12 * 1024 * 1024
IMAGE_PREFIX = '/api/org/robot-messages/public-images/'
TAGS = {'p', 'div', 'br', 'b', 'strong', 'i', 'em', 'u', 'span', 'ul', 'ol', 'li', 'a', 'h2', 'h3', 'blockquote', 'pre', 'code', 'img'}
BLOCKED = {'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'template'}
FORMATS = {'PNG': ('image/png', 'png'), 'JPEG': ('image/jpeg', 'jpg'), 'GIF': ('image/gif', 'gif'), 'WEBP': ('image/webp', 'webp')}
WEB_URL = re.compile(r'''(?<![A-Za-z0-9_/@])https?://[^\s<>"'\x00-\x20\x7f，。；！？、【】（）《》「」『』“”‘’]+''', re.I)


def parse_send_body(request, *, max_bytes=None):
    limit = MAX_REQUEST_BYTES if max_bytes is None else max_bytes
    raw = request.read(limit + 1)
    if len(raw) > limit:
        raise OrganizationAccessError('请求内容超过大小限制，请减少内容后重试', status=413)
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise OrganizationAccessError('请求 JSON 格式错误')
    if not isinstance(payload, dict):
        raise OrganizationAccessError('请求 JSON 必须是对象')
    return payload


def safe_link(value):
    value = str(value or '').strip()
    if any(ord(c) < 32 for c in value):
        return ''
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ''
    return value if parsed.scheme.lower() in {'http', 'https', 'mailto', 'tel'} else ''


def public_origin():
    # Use an explicitly configured public entry point, never a request Host.
    configured = os.getenv('DINGTALK_ROBOT_IMAGE_ORIGIN', '').strip()
    candidates = [configured] if configured else os.getenv('DINGTALK_JSAPI_ALLOWED_ORIGINS', '').split(',')
    for value in candidates:
        try:
            parsed = urlsplit(value.strip())
            parsed.port  # Reject malformed configured ports as well.
        except ValueError:
            continue
        if (parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
                and parsed.path in {'', '/'} and not parsed.query and not parsed.fragment):
            return f'{parsed.scheme}://{parsed.netloc}'
    raise OrganizationAccessError('图片发送地址尚未配置，请联系管理员', code='ROBOT_IMAGE_ORIGIN_MISSING')


def decode_image(source):
    match = re.fullmatch(r'data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)', source, flags=re.I)
    if not match or len(source) > MAX_IMAGE_BYTES * 4 // 3 + 100:
        raise OrganizationAccessError('请使用粘贴或添加图片，单次图片总大小不能超过 8 MB')
    try:
        data = base64.b64decode(match[2], validate=True)
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in FORMATS or image.width * image.height > 20_000_000:
                    raise ValueError
                mime, extension = FORMATS[image.format]
                image.verify()
        if mime != 'image/' + match[1].lower():
            raise ValueError
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise OrganizationAccessError('图片格式或尺寸无效，请使用 PNG、JPG、GIF、WebP，单张不超过 2000 万像素')
    return data, mime, extension


class MessageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {'tag': 'root', 'children': []}
        self.stack = [self.root]
        self.blocked = []
        self.images = []
        self.image_bytes = 0
        self.node_count = 0

    def add(self, node):
        self.node_count += 1
        if self.node_count > 5000 or len(self.stack) > 40:
            raise OrganizationAccessError('消息结构过于复杂，请简化后发送')
        self.stack[-1]['children'].append(node)

    def handle_starttag(self, tag, attrs):
        if self.blocked:
            if tag in BLOCKED:
                self.blocked.append(tag)
            return
        if tag in BLOCKED:
            self.blocked.append(tag)
            return
        if tag not in TAGS:
            return
        attrs = dict(attrs)
        node = {'tag': tag, 'children': []}
        if tag == 'img':
            if len(self.images) >= MAX_IMAGES:
                raise OrganizationAccessError(f'每条消息最多添加 {MAX_IMAGES} 张图片')
            data, mime, extension = decode_image(attrs.get('src') or '')
            self.image_bytes += len(data)
            if self.image_bytes > MAX_IMAGE_BYTES:
                raise OrganizationAccessError('单条消息的图片总大小不能超过 8 MB')
            node['image'] = {'id': uuid.uuid4(), 'token': secrets.token_urlsafe(32), 'data': data, 'mime': mime, 'extension': extension}
            self.images.append(node['image'])
        if tag == 'a':
            node['href'] = safe_link(attrs.get('href'))
        self.add(node)
        if tag not in {'br', 'img'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in {'br', 'img'}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.blocked:
            if tag == self.blocked[-1]:
                self.blocked.pop()
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]['tag'] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not self.blocked:
            self.add(data)


def escape_markdown(text):
    text = html.escape(text, quote=False)
    return re.sub(r'([\\`*_{}\[\]()#+.!|>\-])', r'\\\1', text)


def dingtalk_web_link(url):
    """Use AppLink's mobile full-screen and desktop workbench containers.

    Encode the entire original URL once as the `url` query value. Stored HTML
    keeps its ordinary web link so history also works outside DingTalk.
    """
    try:
        parsed = urlsplit(url)
        parsed.port
        if parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname or any(c.isspace() or ord(c) < 32 for c in url):
            return ''
    except ValueError:
        return ''
    if parsed.hostname.lower() == 'applink.dingtalk.com' and parsed.port in {None, 443}:
        # Native AppLink actions keep their own destination. An existing page
        # link gets the container options directly, without nesting wrappers.
        if parsed.path.rstrip('/') != '/page/link':
            return quote(url, safe=':/?#@!$&*+,;=%')
        options = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                   if key not in {'target', 'targetDesktop'}]
        options.extend([('target', 'fullScreen'), ('targetDesktop', 'workbench')])
        return quote(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(options, quote_via=quote), parsed.fragment)), safe=':/?#@!$&*+,;=%')
    return 'https://applink.dingtalk.com/page/link?url=' + quote(url, safe='') + '&target=fullScreen&targetDesktop=workbench'


def markdown_text(text, linkify=True):
    if not linkify:
        return escape_markdown(text).replace('\n', '\n\n')
    parts, cursor = [], 0
    for match in WEB_URL.finditer(text):
        url = match.group().rstrip('.,;:!?')
        # Sentence delimiters are not part of a pasted URL; balanced URL
        # parentheses (e.g. a wiki path) must survive unchanged.
        excess = {end: url.count(end) - url.count(start) for end, start in [(')', '('), (']', '['), ('}', '{')]}
        while url and url[-1] in excess and excess[url[-1]] > 0:
            excess[url[-1]] -= 1
            url = url[:-1]
        destination = dingtalk_web_link(url)
        if not destination:
            continue
        parts.append(escape_markdown(text[cursor:match.start()]))
        parts.append(f'[{escape_markdown(url)}]({destination})')
        cursor = match.start() + len(url)
    parts.append(escape_markdown(text[cursor:]))
    return ''.join(parts).replace('\n', '\n\n')


def render(node, mode, origin='', linkify=True):
    if isinstance(node, str):
        if mode == 'html':
            return html.escape(node)
        return markdown_text(node, linkify) if mode == 'markdown' else node
    tag = node['tag']
    if tag == 'img':
        image = node['image']
        path = f"{IMAGE_PREFIX}{image['id']}/{image['token']}"
        image['url'] = path
        if mode == 'html':
            return f'<img src="{path}" alt="图片" loading="lazy">'
        return f'\n\n![]({origin}{path})\n\n' if mode == 'markdown' else '\n[图片]\n'
    body = ''.join(render(child, mode, origin, linkify and tag not in {'a', 'code', 'pre'}) for child in node['children'])
    if tag == 'root':
        return body
    if tag == 'br':
        return '<br>' if mode == 'html' else '\n\n' if mode == 'markdown' else '\n'
    if mode == 'html':
        if tag == 'a' and node.get('href'):
            return f'<a href="{html.escape(node["href"], quote=True)}" target="_blank" rel="noopener noreferrer">{body}</a>'
        return f'<{tag}>{body}</{tag}>' if tag != 'a' else body
    if mode == 'markdown':
        if tag in {'b', 'strong'}:
            return f'**{body.strip()}**' if body.strip() else ''
        if tag in {'em', 'i'}:
            return f'*{body.strip()}*' if body.strip() else ''
        if tag == 'a' and node.get('href'):
            url = dingtalk_web_link(node['href']) or quote(node['href'], safe=':/?#@!$&*+,;=%')
            return f'[{body}]({url})'
        if tag in {'h2', 'h3'}:
            return '\n\n' + '#' * int(tag[1]) + ' ' + body.strip() + '\n\n'
        if tag == 'li':
            return '\n- ' + body.strip() + '\n'
        if tag == 'blockquote':
            return '\n\n' + '\n'.join('> ' + line for line in body.strip().splitlines()) + '\n\n'
    if tag in {'p', 'div', 'ul', 'ol', 'li', 'blockquote', 'h2', 'h3', 'pre'}:
        return '\n' + body + '\n'
    return body


def prepare_message(raw):
    if not isinstance(raw, str) or len(raw) > MAX_REQUEST_BYTES or '\x00' in raw:
        raise OrganizationAccessError('图文内容格式无效')
    try:
        fingerprint = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    except UnicodeEncodeError:
        raise OrganizationAccessError('消息包含无效字符')
    parser = MessageParser()
    parser.feed(raw)
    parser.close()
    plain = re.sub(r'\n{3,}', '\n\n', render(parser.root, 'plain')).strip()
    if not plain:
        raise OrganizationAccessError('请填写文字或添加图片')
    origin = public_origin() if parser.images else ''
    markdown = re.sub(r'\n{3,}', '\n\n', render(parser.root, 'markdown', origin)).strip()
    title = next((line.strip() for line in plain.splitlines() if line.strip() != '[图片]'), '图片消息')[:80]
    params = {'title': title or '图文消息', 'text': markdown}
    if len(json.dumps(params, ensure_ascii=False).encode('utf-8')) > 15000:
        raise OrganizationAccessError('消息过长，请缩短文字或减少图片后发送')
    return {'plain': plain, 'html': render(parser.root, 'html'), 'params': params,
            'images': parser.images, 'hash': fingerprint}


def store_images(batch, prepared, saved_files):
    from .models import RobotMessageImage
    for item in prepared['images']:
        image = RobotMessageImage(id=item['id'], batch=batch, access_token=item['token'],
                                  content_type=item['mime'], byte_size=len(item['data']))
        image.file.save(f"{item['id']}.{item['extension']}", ContentFile(item['data']), save=False)
        saved_files.append((image.file.storage, image.file.name))
        image.save()
