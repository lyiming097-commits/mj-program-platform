"""Shared robot delivery pipeline for manual broadcasts and application notifications."""
import hashlib
import re
import secrets
import json
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, Max, OuterRef, Q
from django.http import FileResponse, Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST, require_safe

from .dingtalk.messages import robot_config, send_markdown, send_text, send_message
from .robot_message_types import TEMPLATE_KEYS, prepare_typed_message, validate_message_media
from .models import (Employee, RobotMessageBatch, RobotMessageDelivery, RobotMessageGroup,
                     RobotMessagePermissionState, RobotMessageImage, InternalServiceCredential)
from .org.organization_access import (
    OrganizationAccessError, _OrganizationDirectory, _canonical_permission_rules,
    _error_response, _expected_revision, _parse_json_body, _permission_allows_user,
    _permission_members, can_manage_organization,
)
from .org.queries import employee_matches_keyword, serialize_employee_profiles, has_full_access_user_id
from .org.revision import get_organization_revision, lock_organization_state

from .robot_rich_text import MAX_IMAGES, MAX_IMAGE_BYTES, parse_send_body, prepare_message, store_images

MAX_TARGETS = 100


def can_send(request):
    if can_manage_organization(request):
        return True
    user_id = getattr(request, "auth_user_id", "")
    directory = _OrganizationDirectory()
    if user_id not in directory.employees:
        return False
    rules = RobotMessagePermissionState.objects.filter(pk=1).values_list("rules", flat=True).first() or []
    return _permission_allows_user(rules, user_id)


def denied(request, *, manage=False):
    allowed = can_manage_organization(request) if manage else can_send(request)
    if not allowed:
        return JsonResponse({"code": "ROBOT_MESSAGES_FORBIDDEN", "error":
                             "只有后台管理员可以管理机器人权限和群聊" if manage else "当前账号没有机器人发送权限，请联系后台管理员"}, status=403)
    return None


@require_GET
def capabilities(request):
    _, configured = robot_config()
    return JsonResponse({"canSend": can_send(request), "canManage": can_manage_organization(request),
                         "configured": configured, "maxTargets": MAX_TARGETS,
                         "maxImages": MAX_IMAGES, "maxImageBytes": MAX_IMAGE_BYTES})


def permission_data(state):
    return {"rules": state.rules, "revision": state.revision, "orgRevision": get_organization_revision(),
            "effectiveMembers": _permission_members(state.rules, _OrganizationDirectory()), "canManage": True}


@csrf_exempt
@require_http_methods(["GET", "PUT"])
def permissions(request):
    blocked = denied(request, manage=True)
    if blocked is not None:
        return blocked
    if request.method == "GET":
        state, _ = RobotMessagePermissionState.objects.get_or_create(pk=1)
        return JsonResponse(permission_data(state))
    try:
        payload = _parse_json_body(request)
        with transaction.atomic():
            org = lock_organization_state()
            state, _ = RobotMessagePermissionState.objects.select_for_update().get_or_create(pk=1)
            if not can_manage_organization(request, lock=True):
                return JsonResponse({"error": "管理权限已失效"}, status=403)
            for field, current in (("revision", state.revision), ("orgRevision", org.revision)):
                _expected_revision(payload.get(field), current=current, field_name=field,
                                   required_code="REVISION_REQUIRED", conflict_code="REVISION_CONFLICT")
            state.rules = _canonical_permission_rules(payload.get("rules"), previous_rules=state.rules,
                                                       directory=_OrganizationDirectory())
            state.revision += 1
            state.save()
    except OrganizationAccessError as exc:
        return _error_response(exc)
    return JsonResponse(permission_data(state))


@require_GET
def people(request):
    blocked = denied(request)
    if blocked is not None:
        return blocked
    directory = _OrganizationDirectory()
    keyword = request.GET.get("keyword", "").replace("\x00", "").strip()[:100]
    employees = [e for e in directory.employees.values() if employee_matches_keyword(e, keyword)]
    return JsonResponse({"items": serialize_employee_profiles(employees[:100], include_departments=True),
                         "total": len(employees), "orgRevision": get_organization_revision()})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def groups(request):
    blocked = denied(request, manage=request.method == "POST")
    if blocked is not None:
        return blocked
    robot, _ = robot_config()
    if request.method == "POST":
        try:
            payload = _parse_json_body(request)
            name, cid = payload.get("name"), payload.get("openConversationId")
            if not isinstance(name, str) or not name.isprintable() or not 1 <= len(name.strip()) <= 128:
                raise OrganizationAccessError("请填写群名称（最多 128 字）")
            if not isinstance(cid, str) or not cid.isprintable() or not cid.startswith("cid") or not 4 <= len(cid) <= 256 or any(c.isspace() for c in cid):
                raise OrganizationAccessError("请填写有效的群 openConversationId")
            if not robot:
                raise OrganizationAccessError("尚未配置机器人")
            group, created = RobotMessageGroup.objects.get_or_create(
                robot_code=robot, conversation_id=cid,
                defaults={"name": name.strip(), "created_by": request.auth_user_id},
            )
            if not created:
                return JsonResponse({"error": "该群已经登记，请从群聊列表选择"}, status=409)
        except OrganizationAccessError as exc:
            return _error_response(exc)
        return JsonResponse({"id": group.id, "name": group.name}, status=201)
    records = RobotMessageGroup.objects.filter(robot_code=robot, enabled=True)
    # History counts only deliveries visible to the caller.
    visible = Q(robotmessagedelivery__status="accepted")
    if not can_manage_organization(request):
        visible &= Q(robotmessagedelivery__batch__effective_user_id=request.auth_user_id)
    records = records.annotate(sent_count=Count("robotmessagedelivery", filter=visible),
                               visible_last_sent=Max("robotmessagedelivery__completed_at", filter=visible)).order_by("-sent_count", "name", "id")
    keyword = request.GET.get("keyword", "").replace("\x00", "").strip()[:100]
    if keyword:
        records = records.filter(name__icontains=keyword)
    return JsonResponse({"items": [{"id": g.id, "name": g.name, "sentCount": g.sent_count,
                                     "lastSentAt": g.visible_last_sent.isoformat() if g.visible_last_sent else ""} for g in records]})


def visible_batches(request):
    records = RobotMessageBatch.objects.all()
    if not can_manage_organization(request):
        records = records.filter(effective_user_id=request.auth_user_id)
    return records


def settle_stale_deliveries(batch_ids):
    RobotMessageDelivery.objects.filter(batch_id__in=batch_ids, status="pending",
                                       batch__created_at__lt=timezone.now() - timedelta(hours=1)).update(
        status="failed", message="排队超过一小时，任务已取消，请重新提交", error_code="queue_expired",
        completed_at=timezone.now(),
    )
    RobotMessageDelivery.objects.filter(batch_id__in=batch_ids, status="sending",
                                       started_at__lt=timezone.now() - timedelta(minutes=3)).update(
        status="unknown", message="发送进程未返回结果，请核实钉钉消息", completed_at=timezone.now(),
    )


def batch_data(batch):
    recipients = list(batch.deliveries.order_by("id"))
    states = {r.status for r in recipients}
    state = ("sending" if states & {"pending", "sending"} else "accepted" if states == {"accepted"}
             else "unknown" if "unknown" in states else "partial" if "accepted" in states else "failed")
    return {"id": batch.id, "requestId": str(batch.request_id), "content": batch.content, "status": state,
            "contentHtml": batch.content_html, "messageType": batch.message_key, "message": batch.message_spec,
            "sourceKind": "application" if batch.source_service else "manual",
            "sourceAppId": batch.source_app_id, "sourceService": batch.source_service,
            "businessKey": batch.business_key,
            "images": [{"id": str(image.id), "url": f"/api/org/robot-messages/public-images/{image.id}/{image.access_token}"}
                       for image in batch.images.all()],
            "createdAt": batch.created_at.isoformat(), "senderName": batch.effective_name,
            "actorName": batch.actor_name, "senderUserId": batch.effective_user_id,
            "recipients": [{"id": r.id, "kind": r.kind, "targetName": r.target_name,
                            "userId": r.target_id if r.kind == "person" else None,
                            "groupId": r.group_id, "status": r.status, "message": r.message,
                            "errorCode": r.error_code, "processQueryKey": r.process_query_key,
                            "completedAt": r.completed_at.isoformat() if r.completed_at else ""} for r in recipients]}


@require_GET
def history(request):
    blocked = denied(request)
    if blocked is not None:
        return blocked
    try:
        page = int(request.GET.get("page", "1"))
        if not 1 <= page <= 1_000_000:
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "页码无效"}, status=400)
    records = visible_batches(request)
    group_id = request.GET.get("groupId", "")
    if group_id:
        if len(group_id) > 19 or not group_id.isascii() or not group_id.isdigit() or not 1 <= int(group_id) <= 9223372036854775807:
            return JsonResponse({"error": "群聊筛选无效"}, status=400)
        records = records.filter(deliveries__group_id=int(group_id)).distinct()
    keyword = request.GET.get("keyword", "").replace("\x00", "").strip()[:100]
    if keyword:
        records = records.filter(Q(content__icontains=keyword) | Q(effective_name__icontains=keyword))
    for parameter, lookup in (("sender", "effective_name__icontains"),
                              ("target", "deliveries__target_name__icontains"),
                              ("content", "content__icontains")):
        value = request.GET.get(parameter, "").replace("\x00", "").strip()[:100]
        if value:
            records = records.filter(**{lookup: value}).distinct()
    sent_date = request.GET.get("sentDate", "")
    if sent_date:
        try:
            parsed_date = date.fromisoformat(sent_date)
            if parsed_date.isoformat() != sent_date:
                raise ValueError
        except ValueError:
            return JsonResponse({"error": "发送日期筛选无效"}, status=400)
        records = records.filter(created_at__date=parsed_date)
    status = request.GET.get("status", "")
    if status:
        if status not in {"sending", "accepted", "failed", "unknown", "partial"}:
            return JsonResponse({"error": "发送结果筛选无效"}, status=400)
        # Settle before filtering/counting so expired attempts cannot appear under an outdated status.
        settle_stale_deliveries(records.values("pk"))
        deliveries = RobotMessageDelivery.objects.filter(batch_id=OuterRef("pk"))
        records = records.alias(
            _running=Exists(deliveries.filter(status__in=["pending", "sending"])),
            _accepted=Exists(deliveries.filter(status="accepted")),
            _unknown=Exists(deliveries.filter(status="unknown")),
            _not_accepted=Exists(deliveries.exclude(status="accepted")),
        )
        status_filters = {
            "sending": Q(_running=True),
            "accepted": Q(_running=False, _accepted=True, _not_accepted=False),
            "unknown": Q(_running=False, _unknown=True),
            "partial": Q(_running=False, _unknown=False, _accepted=True, _not_accepted=True),
            "failed": Q(_running=False, _unknown=False, _accepted=False),
        }
        records = records.filter(status_filters[status])
    total = records.count()
    selected = list(records.prefetch_related("images")[(page - 1) * 20:page * 20])
    settle_stale_deliveries([r.id for r in selected])
    return JsonResponse({"items": [batch_data(r) for r in selected], "total": total, "page": page})


@require_GET
def detail(request, request_id):
    blocked = denied(request)
    if blocked is not None:
        return blocked
    batch = visible_batches(request).filter(request_id=request_id).first()
    if batch is None:
        return JsonResponse({"error": "发送记录不存在"}, status=404)
    settle_stale_deliveries([batch.id])
    return JsonResponse(batch_data(batch))


def enqueue_batch(batch_id):
    from .tasks import send_robot_messages_task
    try:
        # Route through CELERY_TASK_ROUTES to the dedicated notification worker.
        send_robot_messages_task.apply_async(args=[batch_id], retry=False)
    except Exception:
        # Publish may have reached the broker: a conditional pending->failed update
        # prevents a subsequently delivered task from sending those recipients.
        RobotMessageDelivery.objects.filter(batch_id=batch_id, status="pending").update(
            status="failed", message="发送任务未能进入队列，请稍后重新提交", error_code="enqueue_failed",
            completed_at=timezone.now(),
        )


@csrf_exempt
@require_POST
def send(request):
    blocked = denied(request)
    if blocked is not None:
        return blocked
    identity = {
        "effective_user_id": request.auth_user_id, "effective_name": request.auth_employee.name,
        "actor_user_id": request.auth_actor_user_id, "actor_name": request.auth_actor_employee.name,
        "source_app_id": "", "source_service": "", "business_key": "",
    }
    try:
        batch, created = submit_message(parse_send_body(request), identity, lambda: can_send(request))
    except OrganizationAccessError as exc:
        return _error_response(exc)
    return JsonResponse(batch_data(batch), status=202 if created else 200)


def submit_message(payload, identity, authorized, *, typed_message=None):
    """Validated callers share persistence, idempotency, recipients, media and queuing."""
    saved_files = []
    committed = False
    try:
        try:
            request_id = uuid.UUID(str(payload.get("requestId", "")))
        except (ValueError, TypeError):
            raise OrganizationAccessError("缺少有效的发送请求编号")
        raw_html = payload.get("contentHtml")
        rich = None
        if typed_message is not None:
            try:
                canonical = json.dumps(typed_message, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
                fingerprint = hashlib.sha256(('typed-message-v1:' + canonical).encode('utf-8')).hexdigest()
            except (ValueError, TypeError, UnicodeError):
                raise OrganizationAccessError("message 必须是有效 JSON 对象") from None
            content = ""
        elif raw_html is not None:
            if not isinstance(raw_html, str):
                raise OrganizationAccessError("图文内容格式无效")
            try:
                fingerprint = hashlib.sha256(raw_html.encode("utf-8")).hexdigest()
            except UnicodeEncodeError:
                raise OrganizationAccessError("消息包含无效字符")
            content = ""
        else:
            fingerprint = ""
            content = payload.get("content")
            if not isinstance(content, str) or not content.strip():
                raise OrganizationAccessError("请填写消息内容")
            try:
                content_size = len(json.dumps({"content": content}, ensure_ascii=False).encode("utf-8"))
            except UnicodeEncodeError:
                raise OrganizationAccessError("消息包含无效字符")
            if "\x00" in content:
                raise OrganizationAccessError("消息包含无效字符")
            if content_size > 15000:
                raise OrganizationAccessError("消息过长，请缩短内容后再发送")
        group_ids, user_ids = payload.get("groupIds", []), payload.get("userIds", [])
        if not isinstance(group_ids, list) or not isinstance(user_ids, list) or not 1 <= len(group_ids) + len(user_ids) <= MAX_TARGETS:
            raise OrganizationAccessError(f"请选择 1 至 {MAX_TARGETS} 个群聊或人员")
        if any(type(i) is not int or not 1 <= i <= 9223372036854775807 for i in group_ids) or any(not isinstance(i, str) or not i or not i.isprintable() or len(i) > 64 for i in user_ids):
            raise OrganizationAccessError("收件对象格式无效，员工 ID 必须为字符串")
        group_ids, user_ids = sorted(set(group_ids)), sorted(set(user_ids))
        old = RobotMessageBatch.objects.filter(request_id=request_id).first()
        if old:
            targets = {(d.kind, d.group_id if d.kind == "group" else d.target_id) for d in old.deliveries.all()}
            if (any(getattr(old, key) != identity[key] for key in (
                    "actor_user_id", "effective_user_id", "source_app_id", "source_service", "business_key"))
                    or (old.payload_hash != fingerprint if fingerprint else old.payload_hash or old.content != content)
                    or targets != ({("group", i) for i in group_ids} | {("person", i) for i in user_ids})):
                raise OrganizationAccessError("请求编号已用于其他发送，请查询原请求", code="REQUEST_CONFLICT", status=409)
            return old, False
        robot, configured = robot_config()
        if not configured:
            raise OrganizationAccessError("尚未配置钉钉机器人凭据", code="ROBOT_NOT_CONFIGURED", status=503)
        if typed_message is not None:
            rich = prepare_typed_message(typed_message, identity)
            content = rich['plain']
        elif raw_html is not None:
            rich = prepare_message(raw_html)
            content = rich["plain"]
        with transaction.atomic():
            lock_organization_state()
            if not authorized():
                raise OrganizationAccessError("发送权限已失效", code="ROBOT_MESSAGES_FORBIDDEN", status=403)
            if typed_message is not None:
                validate_message_media(rich['spec'], identity)
            directory = _OrganizationDirectory()
            selected_groups = list(RobotMessageGroup.objects.filter(id__in=group_ids, enabled=True, robot_code=robot))
            if len(selected_groups) != len(group_ids) or any(i not in directory.employees for i in user_ids):
                raise OrganizationAccessError("收件对象已失效，请重新选择启用群聊或在职员工")
            batch = RobotMessageBatch.objects.create(
                request_id=request_id, robot_code=robot, content=content,
                **identity,
                content_html=rich["html"] if rich else "",
                message_key=rich.get('key', 'sampleMarkdown') if rich else "sampleText",
                message_spec=rich.get('spec', {}) if rich else {},
                message_param=rich["params"] if rich else {}, payload_hash=fingerprint,
            )
            if rich:
                store_images(batch, rich, saved_files)
            RobotMessageDelivery.objects.bulk_create([
                RobotMessageDelivery(batch=batch, kind="group", target_id=g.conversation_id, target_name=g.name, group=g)
                for g in selected_groups
            ] + [RobotMessageDelivery(batch=batch, kind="person", target_id=i, target_name=directory.employees[i].name) for i in user_ids])
            transaction.on_commit(lambda: enqueue_batch(batch.id))
        committed = True
    except IntegrityError:
        raise OrganizationAccessError("同一发送请求正在处理，请查询发送状态", code="REQUEST_CONFLICT", status=409)
    finally:
        if not committed:
            for storage, name in saved_files:
                storage.delete(name)
    return batch, True


@require_safe
def public_image(request, image_id, access_token):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', access_token):
        raise Http404
    image = RobotMessageImage.objects.filter(pk=image_id).first()
    if image is None or not secrets.compare_digest(image.access_token, access_token):
        raise Http404
    try:
        response = FileResponse(image.file.open("rb"), content_type=image.content_type)
    except (FileNotFoundError, OSError):
        raise Http404
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


def application_service_enabled(app_id, service_name):
    return InternalServiceCredential.objects.filter(
        app_id=app_id, service_name=service_name, enabled=True).exists()


def sender_is_valid(batch):
    if batch.source_service:
        return bool(batch.source_app_id and application_service_enabled(batch.source_app_id, batch.source_service))
    employee = Employee.objects.filter(user_id=batch.effective_user_id).first()
    request = SimpleNamespace(auth_user_id=batch.effective_user_id, auth_employee=employee)
    actor = Employee.objects.filter(user_id=batch.actor_user_id).first()
    actor_valid = actor is not None and actor.status == Employee.STATUS_ACTIVE and (
        actor.account_status == Employee.ACCOUNT_ENABLED or has_full_access_user_id(actor.user_id))
    if batch.actor_user_id != batch.effective_user_id:
        actor_valid = actor_valid and has_full_access_user_id(batch.actor_user_id)
    return bool(actor_valid and employee is not None and employee.status == Employee.STATUS_ACTIVE
                and (employee.account_status == Employee.ACCOUNT_ENABLED or has_full_access_user_id(employee.user_id))
                and can_send(request))


def deliver_batch(batch_id):
    batch = RobotMessageBatch.objects.filter(pk=batch_id).first()
    if not batch:
        return
    settle_stale_deliveries([batch.id])
    for recipient in batch.deliveries.filter(status="pending").order_by("id"):
        # Persist the attempt before contacting DingTalk; duplicate queue deliveries
        # can only claim still-pending recipients, never resend uncertain attempts.
        if not RobotMessageDelivery.objects.filter(pk=recipient.pk, status="pending").update(status="sending", started_at=timezone.now()):
            continue
        current_robot, _ = robot_config()
        directory = _OrganizationDirectory()
        if not sender_is_valid(batch):
            result = {"status": "failed", "message": "发送人的账号、应用服务或发送权限已失效"}
        elif batch.created_at < timezone.now() - timedelta(hours=1):
            result = {"status": "failed", "message": "排队超过一小时，任务已取消", "error_code": "queue_expired"}
        elif batch.robot_code != current_robot:
            result = {"status": "failed", "message": "机器人配置已变更，请重新确认后发送"}
        elif recipient.kind == "person" and recipient.target_id not in directory.employees:
            result = {"status": "failed", "message": "收件人已离职、停用或不在启用部门内"}
        elif recipient.kind == "group" and not RobotMessageGroup.objects.filter(pk=recipient.group_id, enabled=True, robot_code=current_robot).exists():
            result = {"status": "failed", "message": "群聊已停用"}
        else:
            try:
                if batch.message_key not in TEMPLATE_KEYS:
                    raise OrganizationAccessError('不支持此消息类型', code='INVALID_ROBOT_MESSAGE')
                validate_message_media(batch.message_spec, {
                    'source_app_id': batch.source_app_id, 'source_service': batch.source_service,
                })
                if batch.message_key == "sampleMarkdown":
                    result = send_markdown(batch.robot_code, recipient.kind, recipient.target_id, batch.message_param)
                elif batch.message_key == 'sampleText':
                    result = send_text(batch.robot_code, recipient.kind, recipient.target_id, batch.content)
                else:
                    result = send_message(batch.robot_code, recipient.kind, recipient.target_id, batch.message_key, batch.message_param)
            except OrganizationAccessError as error:
                result = {'status': 'failed', 'message': str(error), 'error_code': error.code}
            except Exception:
                result = {"status": "unknown", "message": "发送进程异常，请核实钉钉消息", "error_code": "worker_uncertain"}
        RobotMessageDelivery.objects.filter(pk=recipient.pk, status="sending").update(**result, completed_at=timezone.now())
        if result["status"] == "accepted" and recipient.group_id:
            RobotMessageGroup.objects.filter(pk=recipient.group_id).update(last_sent_at=timezone.now())
