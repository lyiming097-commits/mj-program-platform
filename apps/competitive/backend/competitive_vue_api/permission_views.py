import json

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .models import (
    OrganizationDepartment,
    OrganizationEmployee,
    PermissionCode,
    PermissionRule,
    PermissionScope,
    PermissionState,
)
from .org_client import (
    OrganizationServiceError,
    build_department_tree,
    get_organization_snapshot,
    organization_is_configured,
)
from .permissions import access_payload, resolve_permission_access
from .org_sync import refresh_organization_snapshot, sync_organization_snapshot


def _error(detail, status: int) -> JsonResponse:
    return JsonResponse({"detail": detail}, status=status)


def _require_admin(request):
    try:
        access = resolve_permission_access(request)
    except OrganizationServiceError as exc:
        return None, _error(str(exc), exc.status_code)
    if not access.can_manage:
        return access, _error("缺少权限管理权限", 403)
    return access, None


def _serialize_rule(rule: PermissionRule) -> dict:
    return {
        "id": str(rule.id),
        "permission": rule.permission,
        "scopeType": rule.scope_type,
        "targetId": rule.target_id,
        "targetName": rule.target_name,
        "sortOrder": rule.sort_order,
        "createdBy": rule.created_by,
        "createdAt": rule.created_at.isoformat(),
        "updatedAt": rule.updated_at.isoformat(),
    }


def _permission_result() -> dict:
    state, _created = PermissionState.objects.get_or_create(id=1)
    rules = PermissionRule.objects.order_by(
        "permission", "scope_type", "sort_order", "target_name"
    )
    return {"items": [_serialize_rule(rule) for rule in rules], "revision": state.revision}


@require_http_methods(["GET"])
def current_permissions(request):
    try:
        refresh_organization_snapshot()
    except OrganizationServiceError:
        pass
    try:
        access = resolve_permission_access(request)
    except OrganizationServiceError as exc:
        return _error(str(exc), exc.status_code)
    return JsonResponse(access_payload(request, access))


@csrf_exempt
@require_http_methods(["GET", "POST"])
def permissions_collection(request):
    _access, error = _require_admin(request)
    if error:
        return error
    if request.method == "GET":
        return JsonResponse(_permission_result())

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _error("请求 JSON 无效", 400)
    items = payload.get("items")
    if not isinstance(items, list) or len(items) > 2000:
        return _error("权限规则格式无效", 422)
    try:
        revision = int(payload.get("revision"))
        requested_org_revision = int(payload.get("orgRevision"))
    except (TypeError, ValueError):
        return _error("revision 和 orgRevision 必须为非负整数", 422)
    if revision < 0 or requested_org_revision < 0:
        return _error("revision 和 orgRevision 必须为非负整数", 422)

    normalized = []
    unique_keys = set()
    for item in items:
        if not isinstance(item, dict):
            return _error("权限规则格式无效", 422)
        permission = str(item.get("permission") or "")
        scope_type = str(item.get("scopeType") or "")
        target_id = str(item.get("targetId") or "").strip()
        target_name = str(item.get("targetName") or "").strip()
        try:
            sort_order = int(item.get("sortOrder") or 0)
        except (TypeError, ValueError):
            return _error("权限规则顺序无效", 422)
        if (
            permission not in PermissionCode.values
            or scope_type not in PermissionScope.values
            or not target_id
            or len(target_id) > 80
            or len(target_name) > 160
            or sort_order < 0
        ):
            return _error("权限规则格式无效", 422)
        key = (permission, scope_type, target_id)
        if key in unique_keys:
            return _error("权限规则存在重复项", 422)
        unique_keys.add(key)
        normalized.append((permission, scope_type, target_id, target_name, sort_order))

    try:
        sync_result = refresh_organization_snapshot(force=True)
    except OrganizationServiceError as exc:
        return _error(str(exc), exc.status_code)
    org_revision = int(sync_result.get("orgRevision") or 0)
    if org_revision != requested_org_revision:
        return _error(
            {
                "code": "ORG_REVISION_CONFLICT",
                "error": "组织架构已更新，请刷新后重新确认权限",
            },
            409,
        )
    department_ids = {
        str(value) for value in OrganizationDepartment.objects.values_list("dept_id", flat=True)
    }
    employee_ids = {
        str(value)
        for value in OrganizationEmployee.objects.filter(
            status="在职", account_status="启用"
        ).values_list("user_id", flat=True)
    }
    for _permission, scope_type, target_id, _name, _order in normalized:
        valid_ids = (
            employee_ids
            if scope_type in {PermissionScope.EMPLOYEE, PermissionScope.EXCLUDED_EMPLOYEE}
            else department_ids
        )
        if target_id not in valid_ids:
            return _error("权限规则包含已失效的部门或人员", 422)

    with transaction.atomic():
        state, _created = PermissionState.objects.select_for_update().get_or_create(id=1)
        if state.revision != revision:
            return _error(
                {
                    "code": "REVISION_CONFLICT",
                    "error": "权限配置已被其他人更新，请刷新后重试",
                },
                409,
            )
        PermissionRule.objects.all().delete()
        PermissionRule.objects.bulk_create(
            [
                PermissionRule(
                    permission=permission,
                    scope_type=scope_type,
                    target_id=target_id,
                    target_name=target_name,
                    sort_order=sort_order,
                    created_by=request.auth_actor_user_id,
                )
                for permission, scope_type, target_id, target_name, sort_order in normalized
            ]
        )
        state.revision += 1
        state.updated_by = request.auth_actor_user_id
        state.save(update_fields=["revision", "updated_by", "updated_at"])
    return JsonResponse({**_permission_result(), "orgRevision": org_revision})


@require_http_methods(["GET"])
def permission_directory(request):
    _access, error = _require_admin(request)
    if error:
        return error
    if not organization_is_configured():
        return JsonResponse(
            {
                "departments": [],
                "employees": [],
                "orgRevision": 0,
                "directorySource": "unconfigured",
                "available": False,
                "message": "钉钉组织接口尚未配置，请设置 Auth 内部接口环境变量",
            }
        )
    try:
        departments, employees, revision = get_organization_snapshot()
        sync_organization_snapshot(departments, employees)
    except OrganizationServiceError as exc:
        return _error(str(exc), exc.status_code)
    active_employees = [
        employee
        for employee in employees
        if str(employee.get("status") or "").strip() == "在职"
        and str(employee.get("accountStatus") or "").strip() == "启用"
    ]
    return JsonResponse(
        {
            "departments": build_department_tree(departments),
            "employees": active_employees,
            "orgRevision": revision,
            "directorySource": "auth",
            "available": True,
            "message": "",
        }
    )
