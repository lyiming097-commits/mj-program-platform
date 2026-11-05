from __future__ import annotations

import json

from django.db import connection, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .models import AppConfigurationRevision, ApprovalCategory, ApprovalTemplate
from .org_client import (
    AuthOrgClientError,
    build_auth_department_tree,
    get_auth_organization_snapshot,
)
from .permissions import (
    APP_PERMISSION_ADMIN,
    get_request_app_permission,
    get_user_category_permission,
    get_user_category_ids,
    list_app_permission_rules,
    replace_app_permission_rules,
)


APP_CONFIGURATION_PERMISSIONS = "permissions"
def _error(message: str, *, status: int, code: str, **extra) -> JsonResponse:
    payload = {
        "ok": False,
        "error": message,
        "code": code,
    }
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _body(request) -> dict | None:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _permission_configuration_snapshot() -> tuple[list[dict], str]:
    with transaction.atomic():
        state, _created = AppConfigurationRevision.objects.select_for_update().get_or_create(
            key=APP_CONFIGURATION_PERMISSIONS,
            defaults={"revision": 1},
        )
        items = list_app_permission_rules()
        revision = str(max(1, int(state.revision or 1)))
    return items, revision


def _lock_configuration_revision(payload: dict):
    expected = str(payload.get("revision") or "").strip()
    state, _created = AppConfigurationRevision.objects.select_for_update().get_or_create(
        key=APP_CONFIGURATION_PERMISSIONS,
        defaults={"revision": 1},
    )
    current = str(max(1, int(state.revision or 1)))
    if not expected:
        return None, _error(
            "缺少权限配置版本，请刷新后重新编辑",
            status=400,
            code="REVISION_REQUIRED",
            revision=current,
        )
    if expected != current:
        return None, _error(
            "权限配置已被其他人修改，请刷新后重新编辑",
            status=409,
            code="REVISION_CONFLICT",
            revision=current,
        )
    return state, None


def _advance_configuration_revision(state: AppConfigurationRevision) -> str:
    state.revision = max(1, int(state.revision or 1)) + 1
    state.save(update_fields=["revision", "updated_at"])
    return str(state.revision)


def _org_revision_conflict(payload: dict, current_revision: int) -> JsonResponse | None:
    expected = str(payload.get("orgRevision") or "").strip()
    current = str(current_revision)
    if not expected:
        return _error(
            "缺少组织架构版本，请刷新权限页面后再保存",
            status=400,
            code="ORG_REVISION_REQUIRED",
            orgRevision=current,
        )
    if expected != current:
        return _error(
            "组织架构已发生变化，请刷新权限页面后再保存",
            status=409,
            code="ORG_REVISION_CONFLICT",
            orgRevision=current,
        )
    return None


def _org_error(exc: AuthOrgClientError) -> JsonResponse:
    return _error(
        str(exc),
        status=exc.status_code,
        code="AUTH_ORG_UNAVAILABLE",
    )


def _ensure_app_admin(request) -> JsonResponse | None:
    try:
        permission = get_request_app_permission(request)
    except AuthOrgClientError as exc:
        return _org_error(exc)
    if permission == APP_PERMISSION_ADMIN:
        return None
    return _error(
        "只有本应用管理员可以配置权限",
        status=403,
        code="APP_ADMIN_REQUIRED",
    )


def health(_request):
    return JsonResponse({"ok": True})


def health_live(_request):
    return JsonResponse({"ok": True})


def health_ready(_request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({
            "ok": False,
            "code": "DATABASE_UNAVAILABLE",
            "database": "unavailable",
        }, status=503)
    return JsonResponse({"ok": True, "database": "ok"})


@require_GET
def employee_directory(request):
    category_id = str(request.GET.get("categoryId") or request.GET.get("category_id") or "").strip()
    if category_id:
        try:
            category = ApprovalCategory.objects.filter(
                pk=int(category_id), deleted_at__isnull=True,
            ).first()
        except (TypeError, ValueError):
            category = None
        if category is None:
            return _error("审批分类不存在", status=404, code="CATEGORY_NOT_FOUND")
        try:
            app_admin = get_request_app_permission(request) == APP_PERMISSION_ADMIN
            category_admin = get_user_category_permission(
                getattr(request, "auth_user_id", ""), category.pk,
            ) == APP_PERMISSION_ADMIN
        except AuthOrgClientError as exc:
            return _org_error(exc)
        if not (app_admin or category_admin):
            return _error("你没有该审批分类的管理权限", status=403, code="CATEGORY_ADMIN_REQUIRED")
    else:
        denied = _ensure_app_admin(request)
        if denied is not None:
            return denied
    try:
        _departments, employees, org_revision = get_auth_organization_snapshot()
    except AuthOrgClientError as exc:
        return _org_error(exc)
    return JsonResponse({
        "items": employees,
        "count": len(employees),
        "orgRevision": org_revision,
        "directorySource": "auth",
    })


@require_GET
def form_option_directory(request):
    template_id = str(request.GET.get("templateId") or "").strip()
    if not template_id.isdigit():
        return _error("请选择审批模板", status=400, code="TEMPLATE_REQUIRED")
    template = ApprovalTemplate.objects.select_related("published_version").filter(
        pk=int(template_id),
        deleted_at__isnull=True,
        status=ApprovalTemplate.STATUS_PUBLISHED,
        published_version__isnull=False,
    ).first()
    if template is None:
        return _error("该审批模板当前不可用", status=404, code="TEMPLATE_NOT_AVAILABLE")

    fields = template.published_version.form_schema.get("fields", [])
    field_types = {
        str(field.get("type") or "").strip()
        for field in fields
        if isinstance(field, dict)
    }
    if not field_types.intersection({"user", "department"}):
        return JsonResponse({
            "employees": [],
            "departments": [],
            "orgRevision": None,
            "directorySource": "not-required",
        })

    try:
        departments, employees, org_revision = get_auth_organization_snapshot()
    except AuthOrgClientError as exc:
        return _org_error(exc)

    public_departments = [
        {
            "deptId": row.get("deptId") or row.get("id"),
            "name": str(row.get("name") or "").strip(),
            "parentDeptId": row.get("parentDeptId"),
        }
        for row in departments
        if isinstance(row, dict) and (row.get("deptId") is not None or row.get("id") is not None)
    ] if "department" in field_types else []
    public_employees = [
        {
            "userId": str(row.get("userId") or row.get("id") or "").strip(),
            "name": str(row.get("rawName") or row.get("name") or "").strip(),
            "departments": [
                {
                    "deptId": department.get("deptId") or department.get("id"),
                    "name": str(department.get("name") or "").strip(),
                }
                for department in row.get("departments", [])
                if isinstance(department, dict)
            ],
        }
        for row in employees
        if isinstance(row, dict) and str(row.get("userId") or row.get("id") or "").strip()
    ] if "user" in field_types else []
    return JsonResponse({
        "employees": public_employees,
        "departments": public_departments,
        "orgRevision": org_revision,
        "directorySource": "auth",
    })


def session(request):
    managed_category_ids: list[int] = []
    try:
        app_permission = get_request_app_permission(request)
        if app_permission != APP_PERMISSION_ADMIN:
            managed_category_ids = get_user_category_ids(request.auth_user_id)
    except AuthOrgClientError:
        # Identity remains valid when the organization directory is temporarily unavailable.
        # Permission checks fail closed until the directory can be read again.
        app_permission = ""
    can_manage_app = app_permission == APP_PERMISSION_ADMIN
    return JsonResponse({
        "ok": True,
        "userId": request.auth_user_id,
        "name": request.auth_user_name,
        "actorUserId": request.auth_actor_user_id,
        "actorName": request.auth_actor_name,
        "isProxying": request.auth_is_proxy,
        "canUseSystemAdmin": request.auth_can_use_system_admin,
        "appPermission": app_permission,
        # Keep this field scoped to global application administration. Category
        # managers use canManageTemplates/managedCategoryIds and must not gain
        # access to the global permission and data-center screens.
        "canManageApp": can_manage_app,
        "canManageTemplates": can_manage_app or bool(managed_category_ids),
        "managedCategoryIds": managed_category_ids,
    })


@csrf_exempt
@require_http_methods(["GET", "POST"])
def permissions_collection(request):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied

    if request.method == "GET":
        items, revision = _permission_configuration_snapshot()
        return JsonResponse({
            "items": items,
            "revision": revision,
        })

    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    items = payload.get("items")
    if not isinstance(items, list):
        return _error("权限数据格式错误", status=400, code="INVALID_PERMISSION_ITEMS")

    try:
        departments, employees, org_revision = get_auth_organization_snapshot()
    except AuthOrgClientError as exc:
        return _org_error(exc)
    conflict = _org_revision_conflict(payload, org_revision)
    if conflict is not None:
        return conflict

    with transaction.atomic():
        revision_state, conflict = _lock_configuration_revision(payload)
        if conflict is not None:
            return conflict
        try:
            saved_items = replace_app_permission_rules(
                items,
                departments=departments,
                employees=employees,
                actor_user_id=(
                    getattr(request, "auth_actor_user_id", "")
                    or getattr(request, "auth_user_id", "")
                ),
            )
        except ValueError as exc:
            return _error(str(exc), status=400, code="INVALID_PERMISSION_RULE")
        next_revision = _advance_configuration_revision(revision_state)

    return JsonResponse({
        "ok": True,
        "items": saved_items,
        "revision": next_revision,
        "orgRevision": org_revision,
    })


@require_GET
def permission_directory(request):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    try:
        departments, employees, org_revision = get_auth_organization_snapshot()
    except AuthOrgClientError as exc:
        return _org_error(exc)
    return JsonResponse({
        "departments": build_auth_department_tree(departments),
        "roles": [],
        "employees": employees,
        "directorySource": "auth",
        "orgRevision": org_revision,
    })
