from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .approval_serializers import serialize_approval_step
from .approval_services import (
    create_approval_step,
    delete_approval_step,
    ensure_default_approval_steps,
    update_approval_step,
    validate_approval_node,
)
from .models import ProjectNode
from .org_client import AuthOrgClientError
from .permissions import APP_PERMISSION_ADMIN, get_request_app_permission
from .services import DomainValidationError, text
from .crm_source import assert_crm_project_access


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
    return _error("只有本应用管理员可以维护售前审批", status=403, code="APP_ADMIN_REQUIRED")


def _approval_node(request, project_id: int, node_key: str) -> ProjectNode:
    node = ProjectNode.objects.select_related("project").get(
        project_id=project_id,
        node_key=text(node_key),
    )
    assert_crm_project_access(request, node.project, write=request.method != "GET")
    validate_approval_node(node)
    return node


@csrf_exempt
@require_http_methods(["GET", "POST"])
def presales_approvals(request, project_id: int, node_key: str):
    denied = _ensure_admin(request)
    if denied is not None:
        return denied
    try:
        node = _approval_node(request, project_id, node_key)
        if request.method == "GET":
            rows = ensure_default_approval_steps(node, request)
            return JsonResponse({
                "items": [serialize_approval_step(row) for row in rows],
                "projectId": project_id,
                "nodeId": node.id,
                "nodeKey": node.node_key,
            })

        payload = _body(request)
        if payload is None:
            return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
        step = create_approval_step(request, node, payload)
        return JsonResponse({"ok": True, "item": serialize_approval_step(step)}, status=201)
    except ProjectNode.DoesNotExist:
        return _error("售前审批节点不存在", status=404, code="PROJECT_NODE_NOT_FOUND")
    except DomainValidationError as exc:
        return _error(str(exc), status=exc.status, code=exc.code)


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def presales_approval_item(request, project_id: int, node_key: str, step_id: int):
    denied = _ensure_admin(request)
    if denied is not None:
        return denied
    if request.method == "DELETE":
        try:
            node = _approval_node(request, project_id, node_key)
            rows = delete_approval_step(request, node, step_id)
            return JsonResponse({
                "ok": True,
                "items": [serialize_approval_step(row) for row in rows],
            })
        except ProjectNode.DoesNotExist:
            return _error("售前审批节点不存在", status=404, code="PROJECT_NODE_NOT_FOUND")
        except DomainValidationError as exc:
            return _error(str(exc), status=exc.status, code=exc.code)

    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    raw_revision = payload.get("expectedRevision")
    try:
        expected_revision = None if raw_revision in (None, "") else int(raw_revision)
        if expected_revision is not None and expected_revision < 0:
            raise ValueError
    except (TypeError, ValueError):
        return _error("审批版本号无效", status=400, code="INVALID_APPROVAL_REVISION")
    try:
        node = _approval_node(request, project_id, node_key)
        step = update_approval_step(
            request,
            node,
            step_id,
            payload,
            expected_revision=expected_revision,
        )
        return JsonResponse({"ok": True, "item": serialize_approval_step(step)})
    except ProjectNode.DoesNotExist:
        return _error("售前审批节点不存在", status=404, code="PROJECT_NODE_NOT_FOUND")
    except DomainValidationError as exc:
        return _error(str(exc), status=exc.status, code=exc.code)
