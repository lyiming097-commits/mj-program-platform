"""Backend-only media uploads. Keep DingTalk credentials and media ownership in Auth."""
import base64
import binascii
import hashlib
import io
import uuid
import warnings
from pathlib import PurePosixPath

import requests
from PIL import Image, UnidentifiedImageError

from .dingtalk.client import DingTalkAPIError, _get_app_access_token
from .dingtalk.messages import robot_config
from .models import RobotMessageMedia
from .org.organization_access import OrganizationAccessError

MAX_UPLOAD_BODY = 28 * 1024 * 1024
MEDIA_LIMITS = {'image': 20 * 1024 * 1024, 'file': 20 * 1024 * 1024,
                'audio': 2 * 1024 * 1024, 'video': 20 * 1024 * 1024}
MEDIA_EXTENSIONS = {'image': {'jpg', 'jpeg', 'png', 'gif', 'bmp'},
                    'file': {'xlsx', 'pdf', 'zip', 'rar', 'doc', 'docx'},
                    'audio': {'amr'}, 'video': {'mp4'}}
MIME_TYPES = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif',
              'bmp': 'image/bmp', 'pdf': 'application/pdf', 'zip': 'application/zip',
              'rar': 'application/vnd.rar', 'doc': 'application/msword',
              'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
              'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
              'amr': 'audio/amr', 'mp4': 'video/mp4'}


def invalid(message, code='INVALID_ROBOT_MEDIA', status=400):
    return OrganizationAccessError(message, code=code, status=status)


def validate_upload(payload):
    kind, name, encoded = payload.get('kind'), payload.get('fileName'), payload.get('contentBase64')
    if not isinstance(kind, str) or kind not in MEDIA_LIMITS:
        raise invalid('素材 kind 须为 image、file、audio 或 video')
    if (not isinstance(name, str) or not name.strip() or len(name) > 255 or not name.isprintable()
            or '/' in name or '\\' in name):
        raise invalid('fileName 须为不含路径的文件名称，最多 255 字')
    extension = PurePosixPath(name).suffix.lower().lstrip('.')
    if extension not in MEDIA_EXTENSIONS[kind]:
        raise invalid('此消息类型不支持该文件格式')
    if not isinstance(encoded, str) or len(encoded) > (MEDIA_LIMITS[kind] + 2) // 3 * 4:
        raise invalid('素材过大或 Base64 格式无效', status=413)
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise invalid('contentBase64 须为标准 Base64，不包含 data: 前缀') from None
    if not data or len(data) > MEDIA_LIMITS[kind]:
        raise invalid('素材为空或超过大小限制')
    if kind == 'image':
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    expected = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'gif': 'GIF', 'bmp': 'BMP'}[extension]
                    if image.format != expected or image.width * image.height > 20_000_000:
                        raise ValueError
                    image.verify()
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise invalid('图片格式与扩展名不符，或超过 2000 万像素') from None
    else:
        signatures = {'pdf': data.startswith(b'%PDF-'), 'zip': data.startswith((b'PK\x03\x04', b'PK\x05\x06')),
                      'docx': data.startswith(b'PK\x03\x04'), 'xlsx': data.startswith(b'PK\x03\x04'),
                      'rar': data.startswith(b'Rar!\x1a\x07'), 'doc': data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'),
                      'amr': data.startswith((b'#!AMR\n', b'#!AMR-WB\n')), 'mp4': data[4:8] == b'ftyp'}
        if not signatures.get(extension):
            raise invalid('文件头与所选格式不符')
    return kind, name, data, MIME_TYPES[extension]


def upload_to_dingtalk(kind, name, data, mime):
    try:
        token = _get_app_access_token()
    except DingTalkAPIError:
        raise invalid('未能获取机器人上传凭据', 'ROBOT_MEDIA_UPLOAD_FAILED', 503) from None
    try:
        response = requests.post('https://oapi.dingtalk.com/media/upload',
                                 params={'access_token': token}, data={'type': 'voice' if kind == 'audio' else kind},
                                 files={'media': (name, data, mime)}, timeout=(5, 20), allow_redirects=False)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        media_id = payload.get('media_id') if isinstance(payload, dict) else None
        if (response.status_code == 200 and isinstance(payload, dict) and payload.get('errcode') in (0, '0')
                and isinstance(media_id, str) and 1 <= len(media_id) <= 1024 and media_id.isprintable()):
            return media_id
    except requests.RequestException:
        pass
    # Upstream exceptions/URLs can contain the token: never echo or log them.
    raise invalid('钉钉素材上传未确认成功，可以重新上传；本操作不会发送通知', 'ROBOT_MEDIA_UPLOAD_FAILED', 502)


def upload_media(payload, app_id, service):
    from .robot_messages import application_service_enabled
    kind, name, data, mime = validate_upload(payload)
    robot, configured = robot_config()
    if not configured:
        raise invalid('尚未配置钉钉机器人凭据', 'ROBOT_NOT_CONFIGURED', 503)
    media_id = upload_to_dingtalk(kind, name, data, mime)
    current_robot, configured = robot_config()
    if not configured or current_robot != robot or not application_service_enabled(app_id, service):
        raise invalid('机器人或应用服务已变更，请重新上传', 'ROBOT_MEDIA_OWNER_CHANGED', 403)
    return RobotMessageMedia.objects.create(source_app_id=app_id, source_service=service, robot_code=robot,
                                           kind=kind, file_name=name, byte_size=len(data), upstream_media_id=media_id,
                                           content_sha256=hashlib.sha256(data).hexdigest())


def resolve_media(value, identity, kind=None):
    try:
        media_id = uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise invalid('mediaId 须为素材上传接口返回的 UUID') from None
    robot, _ = robot_config()
    media = RobotMessageMedia.objects.filter(pk=media_id, source_app_id=identity['source_app_id'],
                                            source_service=identity['source_service'], robot_code=robot).first()
    if media is None:
        raise invalid('素材不存在或不属于当前应用服务及机器人', 'ROBOT_MEDIA_NOT_FOUND', 404)
    if kind is not None and media.kind != kind:
        raise invalid('素材类型与消息类型不匹配')
    return media


def media_data(media):
    return {'id': str(media.id), 'kind': media.kind, 'fileName': media.file_name,
            'byteSize': media.byte_size, 'createdAt': media.created_at.isoformat()}
