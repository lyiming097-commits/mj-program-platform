"""Application notifications authenticated exclusively by registered service credentials."""
import html
import json
import os
import uuid
from pathlib import Path

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .dingtalk.messages import robot_config
from .internal import internal_json_response, require_internal_auth
from .models import RobotMessageBatch, RobotMessageGroup
from .org.organization_access import OrganizationAccessError
from .robot_messages import MAX_TARGETS, application_service_enabled, batch_data, settle_stale_deliveries, submit_message
from .robot_rich_text import MAX_IMAGES, MAX_IMAGE_BYTES, parse_send_body
from . import robot_media, robot_message_types


def caller_payload(request, allowed, *, max_bytes=None):
    denied = require_internal_auth(request, service_name='Robot notifications')
    if denied is not None:
        return None, denied
    try:
        payload = parse_send_body(request, max_bytes=max_bytes)
        if set(payload) - allowed:
            raise OrganizationAccessError('请求包含不支持的字段', code='INVALID_REQUEST')
        return payload, None
    except OrganizationAccessError as error:
        return None, internal_json_response(request, status=error.status, code=error.code, error=str(error))


def application_name(app_id):
    """Only a display snapshot; authorization always uses the registered service."""
    try:
        path = os.getenv('APP_REGISTRY_FILE', '').strip()
        if path:
            registry = json.loads(Path(path).read_text(encoding='utf-8'))
            for app in registry.get('apps', []):
                if app.get('id') == app_id:
                    return str(app.get('name') or app_id)[:255]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return app_id


def message_response(request, batch, *, created=False):
    data = batch_data(batch)
    data['messageRequestId'] = data.pop('requestId')
    # requestId remains the per-HTTP-call trace ID in the shared internal API contract.
    return internal_json_response(request, data, status=202 if created else 200)


@csrf_exempt
@require_POST
def send(request):
    payload, error = caller_payload(request, {'messageRequestId', 'contentHtml', 'content', 'message', 'groupIds', 'userIds', 'businessKey'})
    if error is not None:
        return error
    try:
        if sum(key in payload for key in ('message', 'contentHtml', 'content')) != 1:
            raise OrganizationAccessError('message、contentHtml 和 content 必须且只能填写一个', code='INVALID_REQUEST')
        if 'message' in payload:
            if not isinstance(payload['message'], dict):
                raise OrganizationAccessError('message 必须是对象', code='INVALID_REQUEST')
            content_html = None
        elif 'content' in payload:
            if not isinstance(payload['content'], str) or not payload['content'].strip():
                raise OrganizationAccessError('请填写消息内容', code='INVALID_REQUEST')
            content_html = '<p>' + html.escape(payload['content']).replace('\n', '<br>') + '</p>'
        else:
            content_html = payload['contentHtml']
            if not isinstance(content_html, str):
                raise OrganizationAccessError('contentHtml 必须是字符串', code='INVALID_REQUEST')
        business_key = payload.get('businessKey', '')
        if not isinstance(business_key, str) or len(business_key) > 200 or (business_key and not business_key.isprintable()):
            raise OrganizationAccessError('businessKey 须为不超过 200 字的业务编号', code='INVALID_REQUEST')
        app_id, service = request.internal_service_app_id, request.internal_caller
        name = application_name(app_id)
        identity = {'source_app_id': app_id, 'source_service': service, 'business_key': business_key,
                    'actor_user_id': '', 'effective_user_id': '', 'actor_name': name, 'effective_name': name}
        batch, created = submit_message({
            'requestId': payload.get('messageRequestId'), 'contentHtml': content_html,
            'groupIds': payload.get('groupIds', []), 'userIds': payload.get('userIds', []),
        }, identity, lambda: application_service_enabled(app_id, service), typed_message=payload.get('message'))
    except OrganizationAccessError as error:
        return internal_json_response(request, status=error.status, code=error.code, error=str(error))
    return message_response(request, batch, created=created)


@csrf_exempt
@require_POST
def detail(request):
    payload, error = caller_payload(request, {'messageRequestId'})
    if error is not None:
        return error
    try:
        request_id = uuid.UUID(str(payload.get('messageRequestId', '')))
    except (ValueError, TypeError):
        return internal_json_response(request, status=400, code='INVALID_REQUEST', error='messageRequestId 须为 UUID')
    batch = RobotMessageBatch.objects.filter(request_id=request_id, source_app_id=request.internal_service_app_id,
                                            source_service=request.internal_caller).first()
    if batch is None:
        return internal_json_response(request, status=404, code='NOT_FOUND', error='发送记录不存在')
    settle_stale_deliveries([batch.id])
    return message_response(request, batch)


@csrf_exempt
@require_POST
def groups(request):
    payload, error = caller_payload(request, {'keyword', 'limit', 'offset'})
    if error is not None:
        return error
    keyword, limit, offset = payload.get('keyword', ''), payload.get('limit', 100), payload.get('offset', 0)
    if (not isinstance(keyword, str) or len(keyword) > 100 or (keyword and not keyword.isprintable())
            or type(limit) is not int or not 1 <= limit <= 100
            or type(offset) is not int or not 0 <= offset <= 1_000_000):
        return internal_json_response(request, status=400, code='INVALID_REQUEST', error='群查询参数无效：keyword 最多 100 字，limit 为 1–100，offset 为非负整数')
    robot, configured = robot_config()
    records = RobotMessageGroup.objects.filter(robot_code=robot, enabled=True, name__icontains=keyword.strip()).order_by('name', 'id')
    return internal_json_response(request, {
        'items': [{'id': item.id, 'name': item.name} for item in records[offset:offset + limit]],
        'total': records.count(), 'limit': limit, 'offset': offset, 'configured': configured,
        'maxTargets': MAX_TARGETS, 'maxImages': MAX_IMAGES, 'maxImageBytes': MAX_IMAGE_BYTES,
    })


@csrf_exempt
@require_POST
def capabilities(request):
    _, error = caller_payload(request, set())
    if error is not None:
        return error
    return internal_json_response(request, robot_message_types.capabilities())


@csrf_exempt
@require_POST
def media_upload(request):
    payload, error = caller_payload(request, {'kind', 'fileName', 'contentBase64'}, max_bytes=robot_media.MAX_UPLOAD_BODY)
    if error is not None:
        return error
    try:
        media = robot_media.upload_media(payload, request.internal_service_app_id, request.internal_caller)
    except OrganizationAccessError as error:
        return internal_json_response(request, status=error.status, code=error.code, error=str(error))
    return internal_json_response(request, robot_media.media_data(media), status=201)


@csrf_exempt
@require_POST
def media_detail(request):
    payload, error = caller_payload(request, {'mediaId'})
    if error is not None:
        return error
    try:
        media = robot_media.resolve_media(payload.get('mediaId'), {
            'source_app_id': request.internal_service_app_id, 'source_service': request.internal_caller,
        })
    except OrganizationAccessError as error:
        return internal_json_response(request, status=error.status, code=error.code, error=str(error))
    return internal_json_response(request, robot_media.media_data(media))
