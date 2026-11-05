from __future__ import annotations

import json

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import ServiceCapabilityTag, ServiceProject
from .org_client import AuthOrgClientError
from . import access
from .services import PROJECT_NODE_TEMPLATES, create_audit_fields, text


MAX_TAGS_PER_NODE = 50
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
        allowed = access.manages_service(request)
    except AuthOrgClientError as exc:
        return _error(str(exc), status=exc.status_code, code="AUTH_ORG_UNAVAILABLE")
    if allowed:
        return None
    return _error("只有服务管理员或系统管理员可以维护能力标签", status=403, code="SERVICE_PERMISSION_REQUIRED")


def _node_catalog() -> list[dict]:
    groups = []
    service_labels = dict(ServiceProject.TYPE_CHOICES)
    for service_type in (
        ServiceProject.TYPE_PRESALES,
        ServiceProject.TYPE_MIDSALES,
        ServiceProject.TYPE_AFTERSALES,
    ):
        groups.append({
            "serviceType": service_type,
            "serviceTypeLabel": service_labels[service_type],
            "nodes": [
                {"nodeKey": node_key, "nodeName": node_name}
                for node_key, node_name, _kind, _description in PROJECT_NODE_TEMPLATES[service_type]
            ],
        })
    return groups


def _catalog_response() -> JsonResponse:
    rows = list(ServiceCapabilityTag.objects.all())
    by_node: dict[tuple[str, str], list[ServiceCapabilityTag]] = {}
    for row in rows:
        by_node.setdefault((row.service_type, row.node_key), []).append(row)
    groups = _node_catalog()
    items = []
    for group in groups:
        for node in group["nodes"]:
            tags = by_node.get((group["serviceType"], node["nodeKey"]), [])
            node["abilities"] = [tag.name for tag in tags]
            node["items"] = [
                {"id": tag.id, "name": tag.name, "sortOrder": tag.sort_order}
                for tag in tags
            ]
            items.extend({
                "id": tag.id,
                "serviceType": group["serviceType"],
                "serviceTypeLabel": group["serviceTypeLabel"],
                "nodeKey": node["nodeKey"],
                "nodeName": node["nodeName"],
                "name": tag.name,
                "sortOrder": tag.sort_order,
            } for tag in tags)
    return JsonResponse({"items": items, "groups": groups})


def _validated_target(payload: dict) -> tuple[str, str] | JsonResponse:
    service_type = text(payload.get("serviceType"))
    node_key = text(payload.get("nodeKey"))
    templates = PROJECT_NODE_TEMPLATES.get(service_type)
    if templates is None:
        return _error("服务类型无效", status=400, code="INVALID_SERVICE_TYPE")
    if node_key not in {row[0] for row in templates}:
        return _error("业务节点无效", status=400, code="INVALID_NODE_KEY")
    return service_type, node_key


def _validated_names(payload: dict) -> list[str] | JsonResponse:
    raw_names = payload.get("names")
    if not isinstance(raw_names, list):
        return _error("能力标签必须是列表", status=400, code="INVALID_CAPABILITY_NAMES")
    names = []
    seen = set()
    for raw_name in raw_names:
        name = text(raw_name)
        if not name:
            continue
        if len(name) > MAX_TAG_LENGTH:
            return _error(
                f"能力标签不能超过 {MAX_TAG_LENGTH} 个字符",
                status=400,
                code="CAPABILITY_NAME_TOO_LONG",
            )
        folded = name.casefold()
        if folded in seen:
            return _error("同一节点下的能力标签不能重复", status=400, code="DUPLICATE_CAPABILITY_NAME")
        seen.add(folded)
        names.append(name)
    if not names:
        return _error("每个业务节点至少保留一个能力标签", status=400, code="CAPABILITY_REQUIRED")
    if len(names) > MAX_TAGS_PER_NODE:
        return _error(
            f"每个业务节点最多维护 {MAX_TAGS_PER_NODE} 个能力标签",
            status=400,
            code="CAPABILITY_LIMIT_REACHED",
        )
    return names


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def capability_catalog(request):
    if request.method == "GET":
        return _catalog_response()

    denied = _ensure_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    target = _validated_target(payload)
    if isinstance(target, JsonResponse):
        return target
    names = _validated_names(payload)
    if isinstance(names, JsonResponse):
        return names
    service_type, node_key = target
    audit = create_audit_fields(request)
    with transaction.atomic():
        list(ServiceCapabilityTag.objects.select_for_update().filter(
            service_type=service_type,
            node_key=node_key,
        ))
        ServiceCapabilityTag.objects.filter(
            service_type=service_type,
            node_key=node_key,
        ).delete()
        ServiceCapabilityTag.objects.bulk_create([
            ServiceCapabilityTag(
                service_type=service_type,
                node_key=node_key,
                name=name,
                sort_order=index,
                **audit,
            )
            for index, name in enumerate(names, start=1)
        ])
    return _catalog_response()
