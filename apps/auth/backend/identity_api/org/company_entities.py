from __future__ import annotations

import hashlib
import json
import re

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from ..internal import require_internal_auth
from ..models import PlatformCompanyEntity, PlatformCompanyEntityHistory
from .organization_access import can_manage_organization
from .queries import is_pinyin_initial_keyword, normalize_pinyin_keyword, pinyin_initials, pinyin_text


PROFILE_APP_IDS = {"crm", "production-order-new"}
FIELD_SPECS = (
    ("company_name", "companyName", "公司名称", 255),
    ("tax_number", "taxNumber", "税号", 64),
    ("bank_name", "bankName", "开户银行", 255),
    ("bank_account", "bankAccount", "账号", 64),
    ("address", "address", "地址", 512),
    ("phone", "phone", "电话", 64),
)


class CompanyDirectoryError(ValueError):
    def __init__(self, message, *, status=400, code="INVALID_REQUEST"):
        super().__init__(message)
        self.status, self.code = status, code


def error_response(error):
    return JsonResponse({"ok": False, "code": error.code, "error": str(error)}, status=error.status)


def body(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError) as exc:
        raise CompanyDirectoryError("请求数据格式错误") from exc
    if not isinstance(payload, dict):
        raise CompanyDirectoryError("请求数据必须为 JSON 对象")
    return payload


def positive_id(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value):
        value = int(value)
    if type(value) is not int or not 1 <= value <= 9223372036854775807:
        raise CompanyDirectoryError("id must be a positive integer")
    return value


def serialize_entity(item, *, profile=False):
    data = {"id": item.id, "companyName": item.company_name,
            "pinyin": pinyin_text(item.company_name), "pinyinInitials": pinyin_initials(item.company_name)}
    if profile:
        data.update({key: getattr(item, field) for field, key, _, _ in FIELD_SPECS})
        data.update(category=item.category, revision=item.revision, updatedAt=item.updated_at.isoformat())
    return data


def directory_query(payload, *, profile=False):
    keyword = payload.get("keyword", payload.get("q", ""))
    if keyword is None:
        keyword = ""
    if not isinstance(keyword, str) or len(keyword) > 100:
        raise CompanyDirectoryError("keyword must be a string of at most 100 characters")
    keyword = keyword.strip()
    return_all = payload.get("all", False)
    if isinstance(return_all, str) and return_all.lower() in {"true", "false", "1", "0"}:
        return_all = return_all.lower() in {"true", "1"}
    if type(return_all) is not bool:
        raise CompanyDirectoryError("all must be a boolean")
    if return_all and ("limit" in payload or "offset" in payload):
        raise CompanyDirectoryError("all cannot be combined with limit or offset")
    paging = {}
    if not return_all:
        for field, default in (("limit", 20), ("offset", 0)):
            value = payload.get(field, default)
            if isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value):
                value = int(value)
            if type(value) is not int or value < (1 if field == "limit" else 0) or (field == "limit" and value > 100):
                raise CompanyDirectoryError(f"Invalid {field}")
            paging[field] = value
    records = list(PlatformCompanyEntity.objects.filter(deleted_at__isnull=True))
    revision = hashlib.sha256(json.dumps(
        [(item.id, item.revision) for item in records], separators=(",", ":"),
    ).encode()).hexdigest()
    if payload.get("directoryRevision") and payload["directoryRevision"] != revision:
        raise CompanyDirectoryError("主体目录已更新，请重新加载", status=409, code="DIRECTORY_REVISION_CONFLICT")
    compact = normalize_pinyin_keyword(keyword) if is_pinyin_initial_keyword(keyword) else ""
    name = payload.get("name")
    if name is not None and (not isinstance(name, str) or len(name) > 255):
        raise CompanyDirectoryError("Invalid name")
    items = []
    for record in records:
        if name is not None and record.company_name != name and record.category != name:
            continue
        item = serialize_entity(record, profile=profile)
        if not keyword or keyword.casefold() in item["companyName"].casefold() or keyword.casefold() in record.tax_number.casefold() or keyword in str(item["id"]) or (
            compact and (compact in item["pinyin"] or compact in item["pinyinInitials"])
        ):
            items.append(item)
    page = items if return_all else items[paging["offset"]:paging["offset"] + paging["limit"]]
    return {"ok": True, "directoryRevision": revision, "keyword": keyword,
            "all": return_all, **paging, "total": len(items), "count": len(page), "items": page}


def record_history(request, item, action, before):
    user_id = str(getattr(request, "auth_user_id", "") or "")
    PlatformCompanyEntityHistory.objects.create(
        entity_id=item.id, action=action, effective_user_id=user_id,
        actor_user_id=str(getattr(request, "auth_actor_user_id", "") or user_id),
        before=before, after=serialize_entity(item, profile=True) if action != "delete" else {})


def management_denied(request):
    if not can_manage_organization(request):
        return JsonResponse({"ok": False, "code": "FORBIDDEN", "error": "只有后台管理员可以维护我司主体"}, status=403)
    return None


def field_values(payload):
    values = {}
    for field, key, label, max_length in FIELD_SPECS:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise CompanyDirectoryError(f"请填写{label}")
        if len(value.strip()) > max_length:
            raise CompanyDirectoryError(f"{label}不能超过{max_length}个字符")
        values[field] = value.strip()
    return values


@csrf_exempt
@require_http_methods(["GET", "POST"])
def company_entities(request):
    denied = management_denied(request)
    if denied is not None:
        return denied
    try:
        if request.method == "GET":
            return JsonResponse(directory_query(request.GET, profile=True))
        values = field_values(body(request))
        user_id = str(getattr(request, "auth_user_id", "") or "")
        with transaction.atomic():
            item = PlatformCompanyEntity.objects.create(**values, created_by=user_id, updated_by=user_id)
            record_history(request, item, "create", {})
        return JsonResponse({"ok": True, "item": serialize_entity(item, profile=True)}, status=201)
    except CompanyDirectoryError as exc:
        return error_response(exc)
    except IntegrityError:
        return error_response(CompanyDirectoryError("税号已被其他公司主体使用"))


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
def company_entity(request, entity_id):
    denied = management_denied(request)
    if denied is not None:
        return denied
    try:
        with transaction.atomic():
            item = PlatformCompanyEntity.objects.select_for_update().filter(pk=entity_id, deleted_at__isnull=True).first()
            if item is None:
                raise CompanyDirectoryError("公司主体不存在", status=404, code="COMPANY_ENTITY_NOT_FOUND")
            if request.method == "GET":
                return JsonResponse({"ok": True, "item": serialize_entity(item, profile=True)})
            payload = body(request) if request.method == "PUT" else request.GET
            if str(payload.get("revision", "")) != str(item.revision):
                raise CompanyDirectoryError("主体资料已更新，请重新加载后核对", status=409, code="REVISION_CONFLICT")
            before = serialize_entity(item, profile=True)
            if request.method == "DELETE":
                item.deleted_at = timezone.now()
            else:
                for field, value in field_values(payload).items():
                    setattr(item, field, value)
            item.updated_by = str(getattr(request, "auth_user_id", "") or "")
            item.revision += 1
            item.save()
            record_history(request, item, "delete" if request.method == "DELETE" else "update", before)
        return JsonResponse({"ok": True, "deletedId": item.id} if request.method == "DELETE" else {
            "ok": True, "item": serialize_entity(item, profile=True)})
    except CompanyDirectoryError as exc:
        return error_response(exc)
    except IntegrityError:
        return error_response(CompanyDirectoryError("税号已被其他公司主体使用"))


def internal_query(request, *, get=False, profile=False):
    denied = require_internal_auth(request, service_name="Platform company directory")
    if denied is not None:
        return denied
    if profile and getattr(request, "internal_service_app_id", "") not in PROFILE_APP_IDS:
        return JsonResponse({"ok": False, "code": "COMPANY_PROFILE_FORBIDDEN", "error": "调用应用未获准读取主体业务资料"}, status=403)
    try:
        payload = body(request)
        if not get:
            return JsonResponse(directory_query(payload, profile=profile))
        item = PlatformCompanyEntity.objects.filter(pk=positive_id(payload.get("id")), deleted_at__isnull=True).first()
        if item is None:
            raise CompanyDirectoryError("公司主体不存在", status=404, code="COMPANY_ENTITY_NOT_FOUND")
        return JsonResponse({"ok": True, "item": serialize_entity(item, profile=profile)})
    except CompanyDirectoryError as exc:
        return error_response(exc)


@csrf_exempt
@require_POST
def internal_search(request):
    return internal_query(request)


@csrf_exempt
@require_POST
def internal_get(request):
    return internal_query(request, get=True)


@csrf_exempt
@require_POST
def internal_profile_search(request):
    return internal_query(request, profile=True)


@csrf_exempt
@require_POST
def internal_profile_get(request):
    return internal_query(request, get=True, profile=True)
