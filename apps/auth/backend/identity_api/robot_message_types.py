"""Strict internal message schemas mapped to DingTalk's published robot templates."""
import copy
import html
import json
from urllib.parse import urlsplit

from .org.organization_access import OrganizationAccessError
from .robot_media import resolve_media, MEDIA_LIMITS, MEDIA_EXTENSIONS
from .robot_rich_text import prepare_message, public_origin, dingtalk_web_link

MESSAGE_TYPES = ('text', 'markdown', 'image', 'link', 'actionCard', 'file', 'audio', 'video')
TEMPLATE_KEYS = {'sampleText', 'sampleMarkdown', 'sampleImageMsg', 'sampleLink',
                 'sampleFile', 'sampleAudio', 'sampleVideo', 'sampleActionCard',
                 *(f'sampleActionCard{i}' for i in range(2, 7))}


def invalid(message):
    return OrganizationAccessError(message, code='INVALID_ROBOT_MESSAGE')


def string(value, field, maximum=15000, *, multiline=False):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise invalid(f'{field} 须为非空字符串，最多 {maximum} 字')
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise invalid(f'{field} 包含无效字符') from None
    if any(not c.isprintable() and not (multiline and c in '\n\r\t') for c in value):
        raise invalid(f'{field} 包含无效字符')
    return value


def web_url(value, field):
    value = string(value, field, 4096)
    try:
        parsed = urlsplit(value)
        parsed.port
        valid = parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username and not parsed.password
    except ValueError:
        valid = False
    if not valid or any(c.isspace() for c in value):
        raise invalid(f'{field} 须为完整 HTTP(S) 网址')
    return value


def image_url(value, field):
    value = web_url(value, field)
    if urlsplit(value).scheme != 'https':
        raise invalid(f'{field} 须为钉钉可直接读取的 HTTPS 图片地址')
    return value


def positive_integer(value, field, maximum=2147483647):
    if type(value) is not int or not 1 <= value <= maximum:
        raise invalid(f'{field} 须为 1 至 {maximum} 的整数')
    return value


def plain_html(value):
    return '<p>' + html.escape(value).replace('\n', '<br>') + '</p>'


def body_content(spec):
    if ('text' in spec) == ('contentHtml' in spec):
        raise invalid('消息正文须且只能提供 text（原生 Markdown）或 contentHtml（富文本）之一')
    if 'contentHtml' in spec:
        return prepare_message(spec['contentHtml'])
    text = string(spec['text'], 'text', multiline=True)
    return {'plain': text, 'html': plain_html(text), 'params': {'text': text}, 'images': []}


def validate_message_media(spec, identity):
    kind = spec.get('type')
    if kind in {'file', 'audio', 'video'}:
        resolve_media(spec.get('mediaId'), identity, kind)
    if kind == 'video':
        resolve_media(spec.get('coverMediaId'), identity, 'image')
    if kind == 'link' and 'imageMediaId' in spec:
        resolve_media(spec['imageMediaId'], identity, 'image')


def prepare_typed_message(message, identity):
    if not isinstance(message, dict) or not isinstance(message.get('type'), str) or message['type'] not in MESSAGE_TYPES:
        raise invalid('message.type 不受支持')
    spec = copy.deepcopy(message)
    kind = spec['type']
    allowed = {
        'text': {'text'}, 'markdown': {'title', 'text', 'contentHtml'}, 'image': {'url'},
        'link': {'title', 'text', 'url', 'imageUrl', 'imageMediaId'},
        'actionCard': {'title', 'text', 'contentHtml', 'buttons', 'layout'},
        'file': {'mediaId'}, 'audio': {'mediaId', 'durationMs'},
        'video': {'mediaId', 'coverMediaId', 'durationSeconds', 'width', 'height'},
    }[kind] | {'type'}
    if set(spec) - allowed:
        raise invalid('message 包含该类型不支持的字段')
    prepared = {'images': [], 'spec': spec}
    if kind == 'text':
        text = string(spec.get('text'), 'text', multiline=True)
        prepared.update(key='sampleText', plain=text, html=plain_html(text), params={'content': text})
    elif kind in {'markdown', 'actionCard'}:
        title = string(spec.get('title'), 'title', 200)
        rich = body_content(spec)
        prepared.update(rich)
        prepared['plain'] = title + '\n' + rich['plain']
        prepared['html'] = '<h3>' + html.escape(title) + '</h3>' + rich['html']
        prepared['params'] = {'title': title, 'text': rich['params']['text']}
        if 'contentHtml' in spec:
            # Avoid returning or storing Base64 in message specifications.
            spec['contentHtml'] = rich['html']
        if kind == 'markdown':
            prepared['key'] = 'sampleMarkdown'
        else:
            buttons, layout = spec.get('buttons'), spec.get('layout', 'vertical')
            if not isinstance(buttons, list) or not 1 <= len(buttons) <= 5:
                raise invalid('操作卡片须有 1 至 5 个按钮')
            if layout not in ('vertical', 'horizontal') or (layout == 'horizontal' and len(buttons) != 2):
                raise invalid('横向操作卡片须恰好 2 个按钮；竖向支持 1 至 5 个')
            for button in buttons:
                if not isinstance(button, dict) or set(button) != {'title', 'url'}:
                    raise invalid('每个按钮须且只能包含 title 和 url')
                string(button['title'], 'button.title', 64)
                web_url(button['url'], 'button.url')
            spec['layout'] = layout
            if len(buttons) == 1:
                prepared['key'] = 'sampleActionCard'
                prepared['params'].update(singleTitle=buttons[0]['title'], singleURL=dingtalk_web_link(buttons[0]['url']))
            else:
                prepared['key'] = f'sampleActionCard{6 if layout == "horizontal" else len(buttons)}'
                for index, button in enumerate(buttons, 1):
                    title_key, url_key = (f'buttonTitle{index}', f'buttonUrl{index}') if layout == 'horizontal' else (f'actionTitle{index}', f'actionURL{index}')
                    prepared['params'].update({title_key: button['title'], url_key: dingtalk_web_link(button['url'])})
            for button in buttons:
                prepared['plain'] += '\n' + button['title'] + '：' + button['url']
                prepared['html'] += '<p><a href="' + html.escape(button['url'], quote=True) + '">' + html.escape(button['title']) + '</a></p>'
    elif kind == 'image':
        url = spec.get('url')
        if isinstance(url, str) and url.startswith('data:'):
            rich = prepare_message('<img src="' + html.escape(url, quote=True) + '">')
            prepared.update(rich)
            url = public_origin() + rich['images'][0]['url']
            spec['url'] = url
        else:
            url = image_url(url, 'url')
            prepared.update(plain='图片：' + url, html=plain_html('图片：' + url))
        prepared.update(key='sampleImageMsg', params={'photoURL': url})
    elif kind == 'link':
        title, text = string(spec.get('title'), 'title', 200), string(spec.get('text'), 'text', multiline=True)
        url = web_url(spec.get('url'), 'url')
        if ('imageUrl' in spec) == ('imageMediaId' in spec):
            raise invalid('链接卡片须且只能提供 imageUrl 或 imageMediaId 之一')
        picture = (image_url(spec['imageUrl'], 'imageUrl') if 'imageUrl' in spec
                   else resolve_media(spec['imageMediaId'], identity, 'image').upstream_media_id)
        prepared.update(key='sampleLink', params={'title': title, 'text': text, 'picUrl': picture, 'messageUrl': dingtalk_web_link(url)},
                        plain=title + '\n' + text + '\n' + url,
                        html='<h3>' + html.escape(title) + '</h3>' + plain_html(text) + '<p><a href="' + html.escape(url, quote=True) + '">查看详情</a></p>')
    else:
        media = resolve_media(spec.get('mediaId'), identity, kind)
        if kind == 'file':
            params = {'mediaId': media.upstream_media_id, 'fileName': media.file_name, 'fileType': media.file_name.rsplit('.', 1)[-1].lower()}
            description = '文件：' + media.file_name
            key = 'sampleFile'
        elif kind == 'audio':
            duration = positive_integer(spec.get('durationMs'), 'durationMs')
            params = {'mediaId': media.upstream_media_id, 'duration': str(duration)}
            description = f'语音：{media.file_name}（{duration} 毫秒）'
            key = 'sampleAudio'
        else:
            cover = resolve_media(spec.get('coverMediaId'), identity, 'image')
            duration = positive_integer(spec.get('durationSeconds'), 'durationSeconds')
            params = {'videoMediaId': media.upstream_media_id, 'picMediaId': cover.upstream_media_id,
                      'videoType': 'mp4', 'duration': str(duration)}
            if ('width' in spec) != ('height' in spec):
                raise invalid('视频 width 和 height 须一起提供')
            for field in ('width', 'height'):
                if field in spec:
                    params[field] = str(positive_integer(spec[field], field, 16384))
            description = f'视频：{media.file_name}（{duration} 秒；封面：{cover.file_name}）'
            key = 'sampleVideo'
        prepared.update(key=key, params=params, plain=description, html=plain_html(description))
    if len(json.dumps(prepared['params'], ensure_ascii=False).encode('utf-8')) > 15000:
        raise invalid('消息参数超过钉钉 15,000 字节限制，请缩短正文、按钮或网址')
    return prepared


def capabilities():
    return {'messageTypes': list(MESSAGE_TYPES), 'messageParameterMaxBytes': 15000,
            'actionCard': {'verticalButtons': [1, 2, 3, 4, 5], 'horizontalButtons': [2]},
            'media': {kind: {'maxBytes': limit, 'extensions': sorted(MEDIA_EXTENSIONS[kind])} for kind, limit in MEDIA_LIMITS.items()},
            'desktopLinkTarget': 'workbench', 'legacyContentSupported': True}
