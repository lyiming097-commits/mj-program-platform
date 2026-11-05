from __future__ import annotations

import json

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import RewardPrize
from .org_client import AuthOrgClientError
from .permissions import APP_PERMISSION_ADMIN, get_request_app_permission
from .services import DomainValidationError, create_audit_fields, text, touch_audit


def _error(message: str, *, status: int, code: str) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message, "code": code}, status=status)


def _ensure_settings_admin(request) -> JsonResponse | None:
    claims = getattr(request, "auth_token_claims", {}) or {}
    if claims.get("chn") == "wechat-mini":
        return _error("小程序账号不能维护奖励设置", status=403, code="APP_ADMIN_REQUIRED")
    try:
        if get_request_app_permission(request) == APP_PERMISSION_ADMIN:
            return None
    except AuthOrgClientError as exc:
        return _error(str(exc), status=exc.status_code, code="AUTH_ORG_UNAVAILABLE")
    return _error("只有系统管理员可以维护实物奖品", status=403, code="APP_ADMIN_REQUIRED")


def _body(request) -> dict | None:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _name(payload: dict, *, current_id: int | None = None) -> str:
    name = text(payload.get("name"))
    if not name or len(name) > 255:
        raise DomainValidationError("奖品名称不能为空且不能超过255个字符", code="INVALID_REWARD_PRIZE_NAME")
    if RewardPrize.objects.filter(name__iexact=name).exclude(pk=current_id).exists():
        raise DomainValidationError("奖品名称已存在", code="DUPLICATE_REWARD_PRIZE")
    return name


def _item(prize: RewardPrize) -> dict:
    return {"id": prize.id, "name": prize.name, "enabled": prize.enabled}


def resolve_active_prize(value) -> RewardPrize:
    raw = text(value)
    prize = RewardPrize.objects.filter(pk=int(raw), enabled=True).first() if raw.isdecimal() and 0 < len(raw) <= 18 and int(raw) > 0 else None
    if prize is None:
        raise DomainValidationError("请选择设置中可用的实物奖品", code="INVALID_REWARD_PRIZE")
    return prize


@csrf_exempt
@require_http_methods(["GET", "POST"])
def reward_prizes(request):
    denied = _ensure_settings_admin(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        return JsonResponse({"items": [_item(row) for row in RewardPrize.objects.all()]})
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        name = _name(payload)
        with transaction.atomic():
            prize = RewardPrize.objects.create(name=name, **create_audit_fields(request))
    except DomainValidationError as exc:
        return _error(str(exc), status=exc.status, code=exc.code)
    except IntegrityError:
        return _error("奖品名称已存在", status=400, code="DUPLICATE_REWARD_PRIZE")
    return JsonResponse({"item": _item(prize)}, status=201)


@csrf_exempt
@require_http_methods(["PATCH"])
def reward_prize_item(request, prize_id: int):
    denied = _ensure_settings_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    if not any(key in payload for key in ("name", "enabled")):
        return _error("没有需要更新的内容", status=400, code="EMPTY_REWARD_PRIZE_UPDATE")
    if "enabled" in payload and not isinstance(payload["enabled"], bool):
        return _error("奖品状态无效", status=400, code="INVALID_REWARD_PRIZE_STATUS")
    try:
        with transaction.atomic():
            prize = RewardPrize.objects.select_for_update().filter(pk=prize_id).first()
            if prize is None:
                return _error("奖品不存在", status=404, code="REWARD_PRIZE_NOT_FOUND")
            if "name" in payload:
                prize.name = _name(payload, current_id=prize_id)
            if "enabled" in payload:
                prize.enabled = payload["enabled"]
            touch_audit(prize, request)
            prize.save()
    except DomainValidationError as exc:
        return _error(str(exc), status=exc.status, code=exc.code)
    except IntegrityError:
        return _error("奖品名称已存在", status=400, code="DUPLICATE_REWARD_PRIZE")
    return JsonResponse({"item": _item(prize)})
