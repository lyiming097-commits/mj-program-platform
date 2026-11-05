from __future__ import annotations

import json

from django.http import JsonResponse
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ..models import Department, Employee, OrganizationState, OrganizationSyncRun
from ..tasks import sync_organization_contacts_task
from .administrative_regions import (
    AdministrativeRegionDirectoryUnavailable,
    directory_error_response,
    load_administrative_region_directory,
)
from .queries import (
    build_department_tree,
    department_matches_keyword,
    get_child_department_ids,
    get_department_managers,
    get_department_or_none,
    get_departments_by_ids,
    get_employee_or_none,
    get_employee_departments,
    get_request_permission_user_id,
    get_subtree_department_ids,
    list_employees,
    serialize_department,
    serialize_employee,
    serialize_employee_profile,
    serialize_employee_profiles,
)
from .sync_runs import mark_sync_enqueue_failed, start_sync_run
from .revision import ORGANIZATION_STATE_ID, advance_organization_revision
from .organization_access import can_manage_organization
from .account_operations import changed_accounts, validate_preview, record_account_operation

def _serialize_sync_run(run: OrganizationSyncRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "runId": str(run.run_id),
        "status": run.status,
        "startedBy": run.started_by,
        "startedAt": run.started_at.isoformat() if run.started_at else "",
        "finishedAt": run.finished_at.isoformat() if run.finished_at else "",
        "summary": run.summary or {},
        "error": run.error,
        "updatedAt": run.updated_at.isoformat() if run.updated_at else "",
    }


@csrf_exempt
@require_POST
def sync_contacts(request):
    if not can_manage_organization(request):
        return JsonResponse({"error": "只有组织架构管理员可以同步通讯录"}, status=403)

    start_result = start_sync_run(get_request_permission_user_id(request))
    sync_run = start_result.run
    if not start_result.created:
        return JsonResponse(
            {
                "ok": False,
                "code": "ORG_SYNC_ALREADY_RUNNING",
                "error": "Organization sync is already running",
                "syncRun": _serialize_sync_run(sync_run),
            },
            status=409,
        )

    try:
        task = sync_organization_contacts_task.delay(str(sync_run.run_id))
    except Exception as exc:
        mark_sync_enqueue_failed(sync_run, exc)
        return JsonResponse(
            {"ok": False, "code": "ORG_SYNC_QUEUE_UNAVAILABLE", "error": "同步任务队列暂时不可用"},
            status=503,
        )

    return JsonResponse(
        {"ok": True, "accepted": True, "taskId": task.id, "syncRun": _serialize_sync_run(sync_run)},
        status=202,
    )


@require_GET
def sync_contacts_status(request, run_id=None):
    if not can_manage_organization(request):
        return JsonResponse({"error": "只有组织架构管理员可以查看同步状态"}, status=403)
    latest_run = OrganizationSyncRun.objects.filter(run_id=run_id).first() if run_id else OrganizationSyncRun.objects.first()
    if run_id and latest_run is None:
        return JsonResponse({"error": f"Sync run not found: {run_id}"}, status=404)
    last_synced_at = (
        OrganizationState.objects.filter(state_id=ORGANIZATION_STATE_ID)
        .values_list("synced_at", flat=True)
        .first()
    )
    return JsonResponse({
        "ok": True,
        "syncRun": _serialize_sync_run(latest_run),
        "lastSyncedAt": last_synced_at.isoformat() if last_synced_at else "",
    })


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_int_query_param(value: str | None, field_name: str) -> tuple[int | None, JsonResponse | None]:
    if value is None or value == "":
        return None, None
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, JsonResponse(
            {
                "code": "INVALID_QUERY_PARAM",
                "error": f"{field_name} must be an integer",
            },
            status=400,
        )


def _parse_employee_status_query(
    value: str | None,
    *,
    default: str = Employee.STATUS_ACTIVE,
) -> tuple[str | None, JsonResponse | None]:
    normalized = str(value if value not in (None, "") else default).strip()
    lowered = normalized.lower()
    if normalized == Employee.STATUS_ACTIVE or lowered == "active":
        return Employee.STATUS_ACTIVE, None
    if normalized == Employee.STATUS_INACTIVE or lowered == "inactive":
        return Employee.STATUS_INACTIVE, None
    if lowered in {"all", "*"}:
        return None, None
    return None, JsonResponse(
        {
            "code": "INVALID_QUERY_PARAM",
            "error": "status must be active, inactive or all",
        },
        status=400,
    )


def _can_read_employee_status(request, status: str | None) -> bool:
    return status == Employee.STATUS_ACTIVE or can_manage_organization(request)


def _department_not_found(dept_id: int) -> JsonResponse:
    return JsonResponse({"error": f"Department not found: {dept_id}"}, status=404)


def _employee_not_found(user_id: str) -> JsonResponse:
    return JsonResponse({"error": f"Employee not found: {user_id}"}, status=404)


def _full_access_only_response() -> JsonResponse:
    return JsonResponse({"error": "只有组织架构管理员可以查看和操作离职员工"}, status=403)


def _visible_department_managers(request, department: Department) -> list[Employee]:
    managers = get_department_managers(department)
    if can_manage_organization(request):
        return managers
    return [manager for manager in managers if manager.status != Employee.STATUS_INACTIVE]


def _advance_request_organization_revision(request) -> int:
    revision = advance_organization_revision(state=getattr(request, "organization_state", None))
    request.organization_revision = revision
    return revision


@require_GET
def administrative_regions(request):
    try:
        directory = load_administrative_region_directory()
    except AdministrativeRegionDirectoryUnavailable:
        return directory_error_response()
    return JsonResponse({
        "ok": True,
        "revision": directory.revision,
        "stats": directory.stats,
        "items": directory.tree,
    })


@require_GET
def administrative_region_search(request):
    keyword = str(request.GET.get("keyword") or request.GET.get("q") or "").strip()
    if len(keyword) > 100:
        return JsonResponse({"code": "INVALID_QUERY_PARAM", "error": "keyword is too long"}, status=400)
    try:
        limit = min(max(int(request.GET.get("limit") or 100), 1), 100)
        offset = max(int(request.GET.get("offset") or 0), 0)
    except (TypeError, ValueError):
        return JsonResponse(
            {"code": "INVALID_QUERY_PARAM", "error": "limit and offset must be integers"},
            status=400,
        )
    try:
        directory = load_administrative_region_directory()
    except AdministrativeRegionDirectoryUnavailable:
        return directory_error_response()
    matches = directory.query(keyword) if keyword else []
    items = matches[offset : offset + limit]
    return JsonResponse({
        "ok": True,
        "revision": directory.revision,
        "keyword": keyword,
        "limit": limit,
        "offset": offset,
        "total": len(matches),
        "count": len(items),
        "items": items,
    })


@require_GET
def list_departments(request):
    parent_dept_id_raw = request.GET.get("parentDeptId")
    if parent_dept_id_raw is None:
        departments = get_departments_by_ids(get_child_department_ids(None))
    else:
        parent_dept_id, error = _parse_int_query_param(parent_dept_id_raw, "parentDeptId")
        if error is not None:
            return error
        departments = get_departments_by_ids(get_child_department_ids(parent_dept_id))
    return JsonResponse({"items": [serialize_department(item) for item in departments]})


@require_GET
def department_tree(request):
    root_dept_id_raw = request.GET.get("rootDeptId")
    root_dept_id, error = _parse_int_query_param(root_dept_id_raw, "rootDeptId")
    if error is not None:
        return error
    tree = build_department_tree(root_dept_id) if root_dept_id is not None else build_department_tree()
    return JsonResponse({"items": tree})


@require_GET
def department_search(request):
    keyword = str(request.GET.get("keyword") or request.GET.get("q") or "").strip()
    if not keyword:
        return JsonResponse({"keyword": "", "count": 0, "items": []})
    if len(keyword) > 100:
        return JsonResponse(
            {"code": "INVALID_QUERY_PARAM", "error": "keyword is too long"},
            status=400,
        )
    try:
        limit = min(max(int(request.GET.get("limit") or 20), 1), 100)
    except (TypeError, ValueError):
        return JsonResponse(
            {"code": "INVALID_QUERY_PARAM", "error": "limit must be an integer"},
            status=400,
        )

    matches = [
        department
        for department in Department.objects.all().order_by("dept_id")
        if department_matches_keyword(department, keyword)
    ]
    return JsonResponse(
        {
            "keyword": keyword,
            "total": len(matches),
            "count": min(len(matches), limit),
            "items": [serialize_department(item) for item in matches[:limit]],
        }
    )


@require_GET
def department_detail(request, dept_id: int):
    department = get_department_or_none(dept_id)
    if department is None:
        return _department_not_found(dept_id)

    child_ids = get_child_department_ids(dept_id)
    subtree_ids = get_subtree_department_ids(dept_id)
    managers = _visible_department_managers(request, department)
    manager = managers[0] if managers else None
    return JsonResponse(
        {
            "department": serialize_department(department),
            "manager": serialize_employee(manager) if manager else None,
            "managers": [serialize_employee(item) for item in managers],
            "childDepartmentIds": child_ids,
            "subtreeDepartmentIds": subtree_ids,
            "directEmployeeCount": len(list_employees(department_ids=[dept_id], status=Employee.STATUS_ACTIVE)),
            "subtreeEmployeeCount": len(list_employees(department_ids=subtree_ids, status=Employee.STATUS_ACTIVE)),
        }
    )


@require_GET
def department_manager(request, dept_id: int):
    department = get_department_or_none(dept_id)
    if department is None:
        return _department_not_found(dept_id)

    managers = _visible_department_managers(request, department)
    manager = managers[0] if managers else None
    return JsonResponse(
        {
            "department": serialize_department(department),
            "manager": serialize_employee(manager) if manager else None,
            "managers": [serialize_employee(item) for item in managers],
        }
    )


@require_GET
def department_subdepartments(request, dept_id: int):
    department = get_department_or_none(dept_id)
    if department is None:
        return _department_not_found(dept_id)

    recursive = _parse_bool(request.GET.get("recursive"))
    department_ids = (
        get_subtree_department_ids(dept_id, include_self=False)
        if recursive
        else get_child_department_ids(dept_id)
    )
    departments = get_departments_by_ids(department_ids)
    return JsonResponse(
        {
            "department": serialize_department(department),
            "recursive": recursive,
            "count": len(departments),
            "items": [serialize_department(item) for item in departments],
        }
    )


@require_GET
def department_employees(request, dept_id: int):
    department = get_department_or_none(dept_id)
    if department is None:
        return _department_not_found(dept_id)

    include_sub_departments = _parse_bool(request.GET.get("includeSubDepartments"))
    include_departments = _parse_bool(request.GET.get("includeDepartments"), default=True)
    status, status_error = _parse_employee_status_query(request.GET.get("status"))
    if status_error is not None:
        return status_error
    if not _can_read_employee_status(request, status):
        return _full_access_only_response()
    keyword = (request.GET.get("keyword") or "").strip()

    department_ids = (
        get_subtree_department_ids(dept_id)
        if include_sub_departments
        else [dept_id]
    )
    employees = list_employees(
        department_ids=department_ids,
        status=status,
        keyword=keyword,
    )
    return JsonResponse(
        {
            "department": serialize_department(department),
            "includeSubDepartments": include_sub_departments,
            "includeDepartments": include_departments,
            "departmentIds": department_ids,
            "count": len(employees),
            "items": serialize_employee_profiles(
                employees,
                include_departments=include_departments,
            ),
        }
    )


@require_GET
def employee_detail(request, user_id: str):
    employee = get_employee_or_none(user_id)
    if employee is None:
        return _employee_not_found(user_id)
    if employee.status == Employee.STATUS_INACTIVE and not can_manage_organization(request):
        return _full_access_only_response()

    departments = get_employee_departments(user_id)
    return JsonResponse(
        {
            "employee": serialize_employee(employee),
            "departments": [serialize_department(item) for item in departments],
        }
    )


@require_GET
def employee_list(request):
    department_id_raw = request.GET.get("departmentId")
    include_sub_departments = _parse_bool(request.GET.get("includeSubDepartments"))
    include_departments = _parse_bool(request.GET.get("includeDepartments"))
    status, status_error = _parse_employee_status_query(request.GET.get("status"))
    if status_error is not None:
        return status_error
    if not _can_read_employee_status(request, status):
        return _full_access_only_response()
    keyword = (request.GET.get("keyword") or "").strip()

    department_ids = None
    if department_id_raw:
        department_id, error = _parse_int_query_param(department_id_raw, "departmentId")
        if error is not None:
            return error
        department = get_department_or_none(department_id)
        if department is None:
            return _department_not_found(department_id)
        department_ids = (
            get_subtree_department_ids(department_id)
            if include_sub_departments
            else [department_id]
        )

    employees = list_employees(
        department_ids=department_ids,
        status=status,
        keyword=keyword,
    )
    return JsonResponse(
        {
            "departmentIds": department_ids or [],
            "includeSubDepartments": include_sub_departments,
            "includeDepartments": include_departments,
            "status": status,
            "keyword": keyword,
            "count": len(employees),
            "items": serialize_employee_profiles(
                employees,
                include_departments=include_departments,
            ),
        }
    )


@require_GET
def inactive_employee_list(request):
    if not can_manage_organization(request):
        return _full_access_only_response()

    keyword = (request.GET.get("keyword") or "").strip()
    employees = list_employees(status=Employee.STATUS_INACTIVE, keyword=keyword)
    items = serialize_employee_profiles(
        employees,
        include_departments=False,
    )
    for item, employee in zip(items, employees):
        item["formerDingTalkDepartments"] = employee.former_dingtalk_departments
        item["formerOrganizationRecordedAt"] = (
            employee.former_organization_recorded_at.isoformat()
            if employee.former_organization_recorded_at else ""
        )
    return JsonResponse(
        {
            "keyword": keyword,
            "count": len(items),
            "items": items,
        }
    )


@csrf_exempt
@require_POST
@transaction.atomic
def update_employee_account_status(request, user_id: str):
    if not can_manage_organization(request):
        return JsonResponse({"error": "只有组织架构管理员可以启用或禁用账号"}, status=403)

    employee = get_employee_or_none(user_id)
    if employee is None:
        return _employee_not_found(user_id)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    account_status = str(payload.get("accountStatus") or "").strip()
    if account_status not in {Employee.ACCOUNT_ENABLED, Employee.ACCOUNT_DISABLED}:
        return JsonResponse({"error": "accountStatus must be 启用 or 禁用"}, status=400)
    if employee.status == Employee.STATUS_INACTIVE and account_status != Employee.ACCOUNT_DISABLED:
        return JsonResponse({"error": "离职员工账号不能启用"}, status=400)

    employees = list(changed_accounts(account_status, user_id))
    preview_error = validate_preview(request, payload, account_status, user_id, employees)
    if preview_error is not None:
        return preview_error
    record_account_operation(request, account_status, user_id, employees)
    changed = employee.account_status != account_status
    if changed:
        employee.account_status = account_status
        employee.auth_version += 1
        employee.save(update_fields=["account_status", "auth_version", "updated_at"])
        _advance_request_organization_revision(request)
    return JsonResponse(
        {
            "ok": True,
            "employee": serialize_employee(employee),
        }
    )


@csrf_exempt
@require_POST
@transaction.atomic
def bulk_update_employee_account_status(request):
    if not can_manage_organization(request):
        return JsonResponse({"error": "只有组织架构管理员可以批量启用或禁用账号"}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    account_status = str(payload.get("accountStatus") or "").strip()
    if account_status not in {Employee.ACCOUNT_ENABLED, Employee.ACCOUNT_DISABLED}:
        return JsonResponse({"error": "accountStatus must be 启用 or 禁用"}, status=400)

    queryset = changed_accounts(account_status)
    employees = list(queryset)
    preview_error = validate_preview(request, payload, account_status, "", employees)
    if preview_error is not None:
        return preview_error
    record_account_operation(request, account_status, "", employees)
    changed_count = len(employees)
    if changed_count:
        queryset.update(
            account_status=account_status,
            auth_version=F("auth_version") + 1,
            updated_at=timezone.now(),
        )
        _advance_request_organization_revision(request)

    return JsonResponse(
        {
            "ok": True,
            "accountStatus": account_status,
            "changedCount": changed_count,
            "scope": Employee.STATUS_ACTIVE,
        }
    )


@csrf_exempt
@require_POST
def update_employee_handover(request, user_id: str):
    if not can_manage_organization(request):
        return _full_access_only_response()

    employee = get_employee_or_none(user_id)
    if employee is None:
        return _employee_not_found(user_id)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    handover_user_id = str(payload.get("handoverUserId") or "").strip()
    if employee.status != Employee.STATUS_INACTIVE:
        return JsonResponse({"error": "只有离职员工可以设置交接人"}, status=400)
    if not handover_user_id:
        changed = bool(employee.handover_user_id)
        if changed:
            employee.handover_user_id = ""
            employee.save(update_fields=["handover_user_id", "updated_at"])
            _advance_request_organization_revision(request)
        return JsonResponse({"ok": True, "employee": serialize_employee_profile(employee, include_departments=True)})

    if handover_user_id == user_id:
        return JsonResponse({"error": "handoverUserId cannot be the same employee"}, status=400)

    handover_employee = get_employee_or_none(handover_user_id)
    if handover_employee is None:
        return JsonResponse({"error": f"Employee not found: {handover_user_id}"}, status=404)
    if handover_employee.status != Employee.STATUS_ACTIVE:
        return JsonResponse({"error": "handover employee must be 在职"}, status=400)
    changed = employee.handover_user_id != handover_user_id
    if changed:
        employee.handover_user_id = handover_user_id
        employee.save(update_fields=["handover_user_id", "updated_at"])
        _advance_request_organization_revision(request)
    return JsonResponse(
        {
            "ok": True,
            "employee": serialize_employee_profile(employee, include_departments=True),
        }
    )
