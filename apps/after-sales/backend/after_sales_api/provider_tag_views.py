from __future__ import annotations

import json

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import ProviderTag
from .org_client import AuthOrgClientError
from .permissions import APP_PERMISSION_ADMIN, get_request_app_permission
from .services import create_audit_fields, text


MAX_TAGS = 200
MAX_TAG_LENGTH = 128


def _error(message: str, *, status: int, code: str) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message, "code": code}, status=status)


def _body(request) -> dict | None:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _ensure_admin(request) -> JsonResponse | None:
    try:
        permission = get_request_app_permission(request)
    except AuthOrgClientError as exc:
        return _error(str(exc), status=exc.status_code, code="AUTH_ORG_UNAVAILABLE")
    if permission == APP_PERMISSION_ADMIN:
        return None
    return _error("只有系统管理员可以维护安装人员标签", status=403, code="APP_ADMIN_REQUIRED")


def _catalog_response() -> JsonResponse:
    rows = list(ProviderTag.objects.all())
    return JsonResponse({
        "items": [row.name for row in rows],
        "tags": [
            {"id": row.id, "name": row.name, "sortOrder": row.sort_order}
            for row in rows
        ],
    })


def _validated_names(payload: dict) -> list[str] | JsonResponse:
    raw_names = payload.get("names")
    if not isinstance(raw_names, list):
        return _error("标签数据格式错误", status=400, code="INVALID_PROVIDER_TAGS")
    if len(raw_names) > MAX_TAGS:
        return _error(f"标签不能超过 {MAX_TAGS} 个", status=400, code="PROVIDER_TAG_LIMIT_REACHED")
    names: list[str] = []
    seen: set[str] = set()
    for raw_name in raw_names:
        name = text(raw_name)
        if not name:
            continue
        if len(name) > MAX_TAG_LENGTH:
            return _error(f"标签不能超过 {MAX_TAG_LENGTH} 个字符", status=400, code="PROVIDER_TAG_TOO_LONG")
        folded = name.casefold()
        if folded in seen:
            return _error("标签不能重复", status=400, code="DUPLICATE_PROVIDER_TAG")
        seen.add(folded)
        names.append(name)
    if not names:
        return _error("至少保留一个安装人员标签", status=400, code="PROVIDER_TAG_REQUIRED")
    return names


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def provider_tags(request):
    if request.method == "GET":
        return _catalog_response()

    denied = _ensure_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    names = _validated_names(payload)
    if isinstance(names, JsonResponse):
        return names
    audit = create_audit_fields(request)
    with transaction.atomic():
        ProviderTag.objects.all().delete()
        ProviderTag.objects.bulk_create([
            ProviderTag(name=name, sort_order=index, **audit)
            for index, name in enumerate(names, start=1)
        ])
    return _catalog_response()
