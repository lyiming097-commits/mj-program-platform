from __future__ import annotations

import json

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import ProjectAssignment, ServiceProvider
from .serializers import serialize_provider
from .services import create_audit_fields, text, touch_audit


MAX_PROFILE_LIST_ITEMS = 100
MAX_PROFILE_LIST_ITEM_LENGTH = 128


def _error(message: str, *, status: int, code: str) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message, "code": code}, status=status)


def _body(request) -> dict | None:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _required_user_id(request) -> tuple[str, JsonResponse | None]:
    user_id = text(getattr(request, "auth_user_id", ""))
    if not user_id:
        return "", _error("请先登录", status=401, code="AUTH_REQUIRED")
    return user_id, None


def _require_wechat_channel(request) -> JsonResponse | None:
    claims = getattr(request, "auth_token_claims", {}) or {}
    channel = text(claims.get("chn")) or "dingtalk"
    audience = text(claims.get("aud")) or "platform"
    if channel == "wechat-mini" and audience == "after-sales-mobile":
        return None
    return _error("该接口仅供微信小程序账号使用", status=403, code="WECHAT_ACCOUNT_REQUIRED")


def _profile_text(payload: dict, key: str, label: str, limit: int, *, required: bool = False) -> str:
    value = text(payload.get(key))
    if required and not value:
        raise ValueError(f"{label}不能为空")
    if len(value) > limit:
        raise ValueError(f"{label}不能超过 {limit} 个字符")
    return value


def _profile_list(payload: dict, key: str, label: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{label}格式错误")
    if len(value) > MAX_PROFILE_LIST_ITEMS:
        raise ValueError(f"{label}不能超过 {MAX_PROFILE_LIST_ITEMS} 项")
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{label}格式错误")
        normalized = item.strip()
        if len(normalized) > MAX_PROFILE_LIST_ITEM_LENGTH:
            raise ValueError(f"{label}单项不能超过 {MAX_PROFILE_LIST_ITEM_LENGTH} 个字符")
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _application_fields(payload: dict, *, creating: bool) -> dict:
    fields = {}
    if creating or "name" in payload:
        fields["name"] = _profile_text(payload, "name", "姓名", 128, required=True)
    if creating or "role" in payload:
        role = text(payload.get("role")) or ServiceProvider.ROLE_INSTALLER
        if role not in {value for value, _label in ServiceProvider.ROLE_CHOICES}:
            raise ValueError("人员角色无效")
        fields["role"] = role
    text_fields = {
        "phone": ("phone", "联系电话", 32),
        "city": ("city", "所在城市", 64),
        "bio": ("bio", "人员简介", 5000),
    }
    for source, (target, label, limit) in text_fields.items():
        required_for_create = creating and source in {"phone", "city"}
        if source in payload or required_for_create:
            fields[target] = _profile_text(
                payload,
                source,
                label,
                limit,
                required=required_for_create,
            )
    if "regions" in payload:
        fields["regions"] = _profile_list(payload, "regions", "服务地区")
    if "skills" in payload:
        fields["skills"] = _profile_list(payload, "skills", "服务技能")
    return fields


@csrf_exempt
@require_http_methods(["GET", "DELETE"])
def provider_me(request):
    channel_failure = _require_wechat_channel(request)
    if channel_failure is not None:
        return channel_failure
    user_id, failure = _required_user_id(request)
    if failure is not None:
        return failure
    provider = ServiceProvider.objects.filter(auth_user_id=user_id).first()
    if request.method == "DELETE":
        if provider is None:
            return _error("服务人员档案不存在", status=404, code="SERVICE_PROVIDER_NOT_FOUND")
        with transaction.atomic():
            provider = ServiceProvider.objects.select_for_update().get(pk=provider.pk)
            active_assignment_count = ProjectAssignment.objects.filter(
                provider=provider,
                status__in=[
                    ProjectAssignment.STATUS_ASSIGNED,
                    ProjectAssignment.STATUS_ACCEPTED,
                    ProjectAssignment.STATUS_IN_PROGRESS,
                ],
            ).count()
            provider.name = "已注销服务人员"
            provider.phone = ""
            provider.city = ""
            provider.regions = []
            provider.skills = []
            provider.bio = ""
            provider.certification_status = ServiceProvider.CERT_PAUSED
            touch_audit(provider, request)
            provider.save()
        return JsonResponse(
            {
                "ok": True,
                "activeAssignmentCount": active_assignment_count,
                "message": "服务资格已停用，个人档案已清理；历史项目和任务记录将继续保留。",
            }
        )
    return JsonResponse({"item": serialize_provider(provider) if provider else None})


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def provider_apply(request):
    channel_failure = _require_wechat_channel(request)
    if channel_failure is not None:
        return channel_failure
    user_id, failure = _required_user_id(request)
    if failure is not None:
        return failure
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    if "authUserId" in payload and text(payload.get("authUserId")) != user_id:
        return _error("不能为其他用户提交服务商申请", status=403, code="PROVIDER_USER_FORBIDDEN")

    try:
        with transaction.atomic():
            provider = ServiceProvider.objects.select_for_update().filter(auth_user_id=user_id).first()
            created = provider is None
            fields = _application_fields(payload, creating=created)
            if created:
                provider = ServiceProvider.objects.create(
                    auth_user_id=user_id,
                    identity_source=ServiceProvider.IDENTITY_WECHAT_MINI,
                    certification_status=ServiceProvider.CERT_PENDING,
                    **fields,
                    **create_audit_fields(request),
                )
            else:
                for field, value in fields.items():
                    setattr(provider, field, value)
                provider.certification_status = ServiceProvider.CERT_PENDING
                touch_audit(provider, request)
                provider.save()
    except ValueError as exc:
        return _error(str(exc), status=400, code="INVALID_PROVIDER_APPLICATION")
    except IntegrityError:
        return _error("服务商申请提交冲突，请重试", status=409, code="PROVIDER_APPLICATION_CONFLICT")

    return JsonResponse(
        {"ok": True, "item": serialize_provider(provider)},
        status=201 if created else 200,
    )
