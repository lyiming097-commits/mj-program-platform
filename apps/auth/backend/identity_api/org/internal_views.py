from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from typing import Iterable

from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..internal import parse_json_body, require_internal_auth
from ..models import Department, DepartmentEmployee, DepartmentManager, Employee
from .administrative_regions import (
    AdministrativeRegionDirectoryUnavailable,
    directory_error_response,
    load_administrative_region_directory,
)
from .organization_access import get_platform_enabled_department_ids
from .queries import (
    department_matches_keyword,
    employee_matches_keyword,
    get_employee_departments_map,
    has_full_access_user_id,
    is_pinyin_initial_keyword,
    serialize_department,
    serialize_employee_profiles,
)


MAX_INTERNAL_USER_IDS = 500
MAX_INTERNAL_DEPARTMENT_IDS = 200
MAX_INTERNAL_USER_DEPARTMENT_ITEMS = 500
MAX_INTERNAL_SEARCH_LIMIT = 100


def _json_error(message: str, *, status: int = 400, code: str = "INVALID_REQUEST") -> JsonResponse:
    return JsonResponse({"ok": False, "code": code, "error": message}, status=status)


def _parse_bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_max_depth(value: object) -> tuple[int | None, JsonResponse | None]:
    if value is None or value == "":
        return None, None
    try:
        max_depth = int(value)
    except (TypeError, ValueError):
        return None, _json_error("maxDepth must be a positive integer", status=400)
    if max_depth < 1:
        return None, _json_error("maxDepth must be a positive integer", status=400)
    return max_depth, None


def _parse_limit_offset(payload: dict, *, default_limit: int = 20) -> tuple[int, int, JsonResponse | None]:
    raw_limit = payload.get("limit", default_limit)
    raw_offset = payload.get("offset", 0)
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        return 0, 0, _json_error("limit and offset must be integers", status=400)
    if limit < 1 or limit > MAX_INTERNAL_SEARCH_LIMIT:
        return 0, 0, _json_error(f"limit must be between 1 and {MAX_INTERNAL_SEARCH_LIMIT}", status=400)
    if offset < 0:
        return 0, 0, _json_error("offset must be greater than or equal to 0", status=400)
    return limit, offset, None


def _parse_keyword(payload: dict) -> tuple[str, JsonResponse | None]:
    keyword = str(payload.get("keyword", payload.get("q", "")) or "").strip()
    if len(keyword) > 100:
        return "", _json_error("keyword is too long", status=400)
    return keyword, None


def _parse_employee_status(raw_value: object, *, default: str = "active") -> tuple[str, str | None, JsonResponse | None]:
    value = str(default if raw_value is None or raw_value == "" else raw_value).strip()
    lowered = value.lower()
    if lowered in {"all", "*"}:
        return "all", None, None
    if lowered in {"active", "enabled", "on"} or value == Employee.STATUS_ACTIVE:
        return "active", Employee.STATUS_ACTIVE, None
    if lowered in {"inactive", "disabled", "off"} or value == Employee.STATUS_INACTIVE:
        return "inactive", Employee.STATUS_INACTIVE, None
    return "", None, _json_error("Invalid status", status=400)


def _parse_account_status(raw_value: object, *, default: str = "enabled") -> tuple[str, str | None, JsonResponse | None]:
    value = str(default if raw_value is None or raw_value == "" else raw_value).strip()
    lowered = value.lower()
    if lowered in {"all", "*"}:
        return "all", None, None
    if lowered in {"enabled", "active", "on"} or value == Employee.ACCOUNT_ENABLED:
        return "enabled", Employee.ACCOUNT_ENABLED, None
    if lowered in {"disabled", "inactive", "off"} or value == Employee.ACCOUNT_DISABLED:
        return "disabled", Employee.ACCOUNT_DISABLED, None
    return "", None, _json_error("Invalid accountStatus", status=400)


def _parse_employee_filters(payload: dict) -> tuple[str, str | None, str, str | None, JsonResponse | None]:
    status_key, status_value, status_error = _parse_employee_status(payload.get("status"))
    if status_error is not None:
        return "", None, "", None, status_error
    account_key, account_value, account_error = _parse_account_status(payload.get("accountStatus"))
    if account_error is not None:
        return "", None, "", None, account_error
    return status_key, status_value, account_key, account_value, None


def _apply_employee_filters(queryset, status: str | None, account_status: str | None):
    if status is not None:
        queryset = queryset.filter(status=status)
    if account_status is not None:
        queryset = queryset.filter(account_status=account_status)
    return queryset


def _unique_ordered(values: Iterable) -> list:
    result = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _parse_user_ids(payload: dict, *, field_name: str = "userIds") -> tuple[list[str], JsonResponse | None]:
    raw_values = payload.get(field_name)
    if not isinstance(raw_values, list):
        return [], _json_error(f"{field_name} must be a list", status=400)
    if len(raw_values) > MAX_INTERNAL_USER_IDS:
        return [], _json_error(f"{field_name} is too large", status=400)
    return [str(item or "").strip() for item in raw_values if str(item or "").strip()], None


def _parse_department_ids(payload: dict, *, field_name: str = "departmentIds") -> tuple[list[int], JsonResponse | None]:
    raw_values = payload.get(field_name)
    if not isinstance(raw_values, list):
        return [], _json_error(f"{field_name} must be a list", status=400)
    if len(raw_values) > MAX_INTERNAL_DEPARTMENT_IDS:
        return [], _json_error(f"{field_name} is too large", status=400)

    department_ids: list[int] = []
    for raw_value in raw_values:
        try:
            department_ids.append(int(raw_value))
        except (TypeError, ValueError):
            return [], _json_error(f"Invalid department id: {raw_value!r}", status=400)
    return department_ids, None


def _parse_optional_department_ids(
    payload: dict,
    *,
    field_name: str = "departmentIds",
) -> tuple[list[int] | None, JsonResponse | None]:
    if field_name not in payload:
        return None, None
    return _parse_department_ids(payload, field_name=field_name)


def _parse_user_department_items(payload: dict) -> tuple[list[dict], JsonResponse | None]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return [], _json_error("items must be a list", status=400)
    if len(raw_items) > MAX_INTERNAL_USER_DEPARTMENT_ITEMS:
        return [], _json_error("items is too large", status=400)

    items: list[dict] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            return [], _json_error(f"items[{index}] must be an object", status=400)
        user_id = str(raw_item.get("userId") or raw_item.get("user_id") or "").strip()
        if not user_id:
            return [], _json_error(f"items[{index}].userId is required", status=400)
        department_raw = raw_item.get("departmentId", raw_item.get("deptId"))
        try:
            department_id = int(department_raw)
        except (TypeError, ValueError):
            return [], _json_error(f"items[{index}].departmentId must be an integer", status=400)
        items.append({"userId": user_id, "departmentId": department_id})
    return items, None


def _internal_payload(request) -> tuple[dict, JsonResponse | None]:
    auth_error = require_internal_auth(request, service_name="Internal organization API")
    if auth_error is not None:
        return {}, auth_error
    return parse_json_body(request), None


def _load_department_context() -> tuple[dict[int, Department], dict[int | None, list[Department]]]:
    enabled_ids = get_platform_enabled_department_ids()
    departments = list(Department.objects.filter(dept_id__in=enabled_ids).order_by("dept_id"))
    departments_by_id = {department.dept_id: department for department in departments}
    children_by_parent: dict[int | None, list[Department]] = defaultdict(list)
    for department in departments:
        parent_id = department.parent_dept_id
        if parent_id not in departments_by_id:
            parent_id = None
        children_by_parent[parent_id].append(department)
    return departments_by_id, children_by_parent


def _department_manager_user_ids(department: Department) -> list[str]:
    manager_user_ids = [
        str(user_id or "").strip()
        for user_id in (department.manager_user_ids or [])
        if str(user_id or "").strip()
    ]
    if not manager_user_ids and str(department.manager_user_id or "").strip():
        manager_user_ids = [str(department.manager_user_id).strip()]
    return list(dict.fromkeys(manager_user_ids))


def _managed_departments_by_user_id(user_ids: list[str]) -> dict[str, list[Department]]:
    normalized_user_ids = _unique_ordered(user_ids)
    enabled_ids = get_platform_enabled_department_ids()
    result: dict[str, list[Department]] = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    relations = (
        DepartmentManager.objects.filter(
            employee_id__in=normalized_user_ids,
            department_id__in=enabled_ids,
        )
        .select_related("department")
        .order_by("employee_id", "department_id", "sort_order")
    )
    for relation in relations:
        key = (relation.employee_id, relation.department_id)
        if key not in seen:
            seen.add(key)
            result[relation.employee_id].append(relation.department)

    for department in Department.objects.filter(
        manager_user_id__in=normalized_user_ids,
        dept_id__in=enabled_ids,
    ).order_by("dept_id"):
        key = (department.manager_user_id, department.dept_id)
        if key not in seen:
            seen.add(key)
            result[department.manager_user_id].append(department)
    return result


def _department_chain_to_root(
    department_id: int,
    departments_by_id: dict[int, Department],
    *,
    max_depth: int | None = None,
) -> list[Department]:
    chain: list[Department] = []
    visited: set[int] = set()
    current = departments_by_id.get(department_id)
    while current is not None:
        if current.dept_id in visited:
            break
        visited.add(current.dept_id)
        chain.append(current)
        if max_depth is not None and len(chain) >= max_depth:
            break
        if current.parent_dept_id is None:
            break
        current = departments_by_id.get(current.parent_dept_id)
    return chain


def _department_path(
    department: Department,
    departments_by_id: dict[int, Department],
) -> list[Department]:
    return list(reversed(_department_chain_to_root(department.dept_id, departments_by_id)))


def _serialize_department_with_path(
    department: Department,
    departments_by_id: dict[int, Department],
    *,
    include_department_path: bool = False,
) -> dict:
    payload = serialize_department(department)
    if department.parent_dept_id not in departments_by_id:
        payload["parentDeptId"] = None
    if include_department_path:
        path = _department_path(department, departments_by_id)
        payload["departmentPath"] = [
            {
                **serialize_department(item),
                "parentDeptId": item.parent_dept_id if item.parent_dept_id in departments_by_id else None,
            }
            for item in path
        ]
        payload["departmentPathText"] = " / ".join(str(item.name or "") for item in path)
    return payload


def _enrich_employee_department_paths(
    profiles: list[dict],
    departments_by_id: dict[int, Department],
    *,
    include_department_path: bool,
) -> list[dict]:
    for profile in profiles:
        departments = []
        for department_payload in profile.get("departments") or []:
            department = departments_by_id.get(department_payload.get("deptId"))
            if department is None:
                continue
            departments.append(
                _serialize_department_with_path(
                    department,
                    departments_by_id,
                    include_department_path=include_department_path,
                )
            )
        profile["departments"] = departments
    return profiles


def _serialize_employee_list(
    employees: Iterable[Employee],
    departments_by_id: dict[int, Department],
    *,
    include_departments: bool = False,
    include_department_path: bool = False,
) -> list[dict]:
    profiles = serialize_employee_profiles(
        employees,
        include_departments=include_departments or include_department_path,
    )
    for profile in profiles:
        profile["isSystemAdmin"] = has_full_access_user_id(profile.get("userId"))
    return _enrich_employee_department_paths(
        profiles,
        departments_by_id,
        include_department_path=include_department_path,
    )


def _load_employee_profile_map(
    user_ids: Iterable[str],
    departments_by_id: dict[int, Department],
    *,
    status: str | None,
    account_status: str | None,
    include_departments: bool = False,
    include_department_path: bool = False,
) -> dict[str, dict]:
    unique_user_ids = _unique_ordered([str(user_id or "").strip() for user_id in user_ids if str(user_id or "").strip()])
    if not unique_user_ids:
        return {}
    employees = list(
        _apply_employee_filters(
            Employee.objects.filter(
                identity_source=Employee.IDENTITY_DINGTALK,
                user_id__in=unique_user_ids,
                department_employees__department_id__in=departments_by_id,
            ).order_by("user_id"),
            status,
            account_status,
        ).distinct()
    )
    return {
        item["userId"]: item
        for item in _serialize_employee_list(
            employees,
            departments_by_id,
            include_departments=include_departments,
            include_department_path=include_department_path,
        )
    }


def _collect_subtree_department_ids(
    root_dept_id: int,
    children_by_parent: dict[int | None, list[Department]],
    *,
    include_self: bool,
) -> list[int]:
    result: list[int] = []
    queue: deque[int] = deque([root_dept_id])
    visited: set[int] = set()
    while queue:
        current_id = queue.popleft()
        if current_id in visited:
            continue
        visited.add(current_id)
        if include_self or current_id != root_dept_id:
            result.append(current_id)
        for child in children_by_parent.get(current_id, []):
            queue.append(child.dept_id)
    return result


def _department_scope_ids(
    department_ids: list[int] | None,
    departments_by_id: dict[int, Department],
    children_by_parent: dict[int | None, list[Department]],
    *,
    include_sub_departments: bool,
) -> list[int] | None:
    if department_ids is None:
        return None
    scope_ids: list[int] = []
    for department_id in _unique_ordered(department_ids):
        if department_id not in departments_by_id:
            continue
        if include_sub_departments:
            scope_ids.extend(_collect_subtree_department_ids(department_id, children_by_parent, include_self=True))
        else:
            scope_ids.append(department_id)
    return _unique_ordered(scope_ids)


def _membership_pairs(user_ids: Iterable[str], department_ids: Iterable[int]) -> set[tuple[str, int]]:
    normalized_user_ids = _unique_ordered([str(user_id or "").strip() for user_id in user_ids if str(user_id or "").strip()])
    normalized_department_ids = _unique_ordered(list(department_ids))
    if not normalized_user_ids or not normalized_department_ids:
        return set()
    return set(
        DepartmentEmployee.objects.filter(
            employee_id__in=normalized_user_ids,
            department_id__in=normalized_department_ids,
        ).values_list("employee_id", "department_id")
    )


def _department_members_map(department_ids: Iterable[int]) -> dict[int, set[str]]:
    normalized_department_ids = _unique_ordered(list(department_ids))
    members_by_department_id: dict[int, set[str]] = defaultdict(set)
    if not normalized_department_ids:
        return members_by_department_id
    for department_id, employee_id in DepartmentEmployee.objects.filter(
        department_id__in=normalized_department_ids,
    ).values_list("department_id", "employee_id"):
        members_by_department_id[department_id].add(employee_id)
    return members_by_department_id


def _employees_for_department_ids(
    department_ids: Iterable[int],
    departments_by_id: dict[int, Department],
    *,
    status: str | None,
    account_status: str | None,
    include_departments: bool = False,
    include_department_path: bool = False,
) -> list[dict]:
    normalized_department_ids = _unique_ordered(list(department_ids))
    if not normalized_department_ids:
        return []
    employee_ids = list(
        DepartmentEmployee.objects.filter(
            department_id__in=normalized_department_ids,
        )
        .order_by("employee_id")
        .values_list("employee_id", flat=True)
        .distinct()
    )
    employees = list(
        _apply_employee_filters(
            Employee.objects.filter(
                identity_source=Employee.IDENTITY_DINGTALK,
                user_id__in=employee_ids,
            ).order_by("user_id"),
            status,
            account_status,
        )
    )
    return _serialize_employee_list(
        employees,
        departments_by_id,
        include_departments=include_departments,
        include_department_path=include_department_path,
    )


def _response_meta(
    *,
    status_key: str | None = None,
    account_status_key: str | None = None,
    include_department_path: bool | None = None,
    include_sub_departments: bool | None = None,
    max_depth: int | None = None,
) -> dict:
    payload: dict = {}
    if status_key is not None:
        payload["status"] = status_key
    if account_status_key is not None:
        payload["accountStatus"] = account_status_key
    if include_department_path is not None:
        payload["includeDepartmentPath"] = include_department_path
    if include_sub_departments is not None:
        payload["includeSubDepartments"] = include_sub_departments
    if max_depth is not None:
        payload["maxDepth"] = max_depth
    return payload


@csrf_exempt
@require_POST
def internal_users_search(request):
    payload, error = _internal_payload(request)
    if error is not None:
        return error

    keyword, error = _parse_keyword(payload)
    if error is not None:
        return error
    limit, offset, error = _parse_limit_offset(payload)
    if error is not None:
        return error
    status_key, status_value, account_key, account_value, error = _parse_employee_filters(payload)
    if error is not None:
        return error
    department_ids, error = _parse_optional_department_ids(payload)
    if error is not None:
        return error
    include_sub_departments = _parse_bool(payload.get("includeSubDepartments"))
    include_department_path = _parse_bool(payload.get("includeDepartmentPath"))
    include_departments = _parse_bool(payload.get("includeDepartments"), default=include_department_path)

    departments_by_id, children_by_parent = _load_department_context()
    scope_department_ids = _department_scope_ids(
        department_ids,
        departments_by_id,
        children_by_parent,
        include_sub_departments=include_sub_departments,
    )

    queryset = Employee.objects.filter(
        identity_source=Employee.IDENTITY_DINGTALK,
        department_employees__department_id__in=departments_by_id,
    ).distinct().order_by("name", "user_id")
    queryset = _apply_employee_filters(queryset, status_value, account_value)
    use_python_keyword_filter = bool(keyword and is_pinyin_initial_keyword(keyword))
    if keyword and not use_python_keyword_filter:
        queryset = queryset.filter(Q(name__icontains=keyword) | Q(user_id__icontains=keyword))
    if scope_department_ids is not None:
        if not scope_department_ids:
            queryset = queryset.none()
        else:
            scoped_user_ids = DepartmentEmployee.objects.filter(
                department_id__in=scope_department_ids,
            ).values_list("employee_id", flat=True)
            queryset = queryset.filter(user_id__in=scoped_user_ids).distinct()

    if use_python_keyword_filter:
        matched_employees = [employee for employee in queryset if employee_matches_keyword(employee, keyword)]
        total = len(matched_employees)
        employees = matched_employees[offset : offset + limit]
    else:
        total = queryset.count()
        employees = list(queryset[offset : offset + limit])
    items = _serialize_employee_list(
        employees,
        departments_by_id,
        include_departments=include_departments,
        include_department_path=include_department_path,
    )
    return JsonResponse(
        {
            "ok": True,
            **_response_meta(
                status_key=status_key,
                account_status_key=account_key,
                include_department_path=include_department_path,
                include_sub_departments=include_sub_departments if department_ids is not None else None,
            ),
            "keyword": keyword,
            "limit": limit,
            "offset": offset,
            "departmentIds": department_ids or [],
            "scopeDepartmentIds": scope_department_ids or [],
            "total": total,
            "count": len(items),
            "items": items,
        }
    )


@csrf_exempt
@require_POST
def internal_administrative_regions_search(request):
    payload, error = _administrative_region_payload(request)
    if error is not None:
        return error
    keyword, error = _parse_keyword(payload)
    if error is not None:
        return error
    for field, default in (("limit", 100), ("offset", 0)):
        raw_value = payload.get(field, default)
        if type(raw_value) is not int and (
            not isinstance(raw_value, str) or not re.fullmatch(r"-?[0-9]{1,19}", raw_value)
        ):
            return _json_error("limit and offset must be integers")
    limit, offset, error = _parse_limit_offset(payload, default_limit=100)
    if error is not None:
        return error
    level = payload.get("level", "")
    if level not in ("", "province", "city", "district"):
        return _json_error("level must be province, city or district")
    parent_code, error = _administrative_region_code(payload, "parentCode", optional=True)
    if error is not None:
        return error
    try:
        directory = load_administrative_region_directory()
    except AdministrativeRegionDirectoryUnavailable:
        return directory_error_response()
    if payload.get("revision") and payload["revision"] != directory.revision:
        return _json_error("区域目录版本已更新，请重新获取快照", status=409, code="REGION_REVISION_CONFLICT")
    if "city" in payload and "province" not in payload:
        return _json_error("使用城市名称查询时必须同时指定省份")
    if "province" in payload:
        province = payload["province"]
        if not isinstance(province, str) or not province.strip():
            return _json_error("province must be a non-empty name or code")
        matches = [row for row in directory.items if row["level"] == "province" and province.strip() in (row["name"], row["code"])]
        if len(matches) != 1:
            return _json_error("省份不存在", status=404, code="REGION_NOT_FOUND")
        scope_code = matches[0]["code"]
        if "city" in payload:
            city = payload["city"]
            if not isinstance(city, str) or not city.strip():
                return _json_error("city must be a non-empty name or code")
            matches = [row for row in directory.items if row["level"] == "city" and row["parentCode"] == scope_code
                       and city.strip() in (row["name"], row["code"])]
            if len(matches) != 1:
                return _json_error("该省下不存在所选城市", status=404, code="REGION_NOT_FOUND")
            scope_code = matches[0]["code"]
        if parent_code is not None and parent_code != scope_code:
            return _json_error("parentCode 与省市范围不一致")
        parent_code = scope_code
    if parent_code and parent_code not in directory.by_code:
        return _json_error("父级行政区不存在", status=404, code="REGION_NOT_FOUND")
    matches = directory.query(keyword, level=level, parent_code=parent_code)
    items = matches[offset : offset + limit]
    return JsonResponse({
        "ok": True,
        "revision": directory.revision,
        "keyword": keyword,
        "level": level,
        "parentCode": parent_code,
        "limit": limit,
        "offset": offset,
        "total": len(matches),
        "count": len(items),
        "items": items,
    })


def _administrative_region_payload(request) -> tuple[dict, JsonResponse | None]:
    error = require_internal_auth(request, service_name="Internal administrative region API")
    if error is not None:
        return {}, error
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, _json_error("请求数据格式错误")
    if not isinstance(payload, dict):
        return {}, _json_error("请求数据必须为 JSON 对象")
    return payload, None


def _administrative_region_code(
    payload: dict, field: str, *, optional: bool = False,
) -> tuple[str | None, JsonResponse | None]:
    if optional and field not in payload:
        return None, None
    value = payload.get(field)
    if optional and value == "":
        return "", None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{6}", value):
        return None, _json_error(f"{field} must be a six-digit string")
    return value, None


@csrf_exempt
@require_POST
def internal_administrative_regions(request):
    payload, error = _administrative_region_payload(request)
    if error is not None:
        return error
    if "ifRevision" in payload and not isinstance(payload["ifRevision"], str):
        return _json_error("ifRevision must be a string")
    try:
        directory = load_administrative_region_directory()
    except AdministrativeRegionDirectoryUnavailable:
        return directory_error_response()
    if payload.get("ifRevision") == directory.revision:
        return JsonResponse({"ok": True, "revision": directory.revision, "notModified": True})
    return JsonResponse({
        "ok": True,
        "revision": directory.revision,
        "stats": directory.stats,
        "items": directory.tree,
    })


@csrf_exempt
@require_POST
def internal_administrative_region_get(request):
    payload, error = _administrative_region_payload(request)
    if error is not None:
        return error
    code, error = _administrative_region_code(payload, "code")
    if error is not None:
        return error
    try:
        directory = load_administrative_region_directory()
    except AdministrativeRegionDirectoryUnavailable:
        return directory_error_response()
    item = directory.by_code.get(code)
    if item is None:
        return _json_error("行政区不存在", status=404, code="REGION_NOT_FOUND")
    return JsonResponse({"ok": True, "revision": directory.revision, "item": item})


@csrf_exempt
@require_POST
def internal_departments_search(request):
    payload, error = _internal_payload(request)
    if error is not None:
        return error

    keyword, error = _parse_keyword(payload)
    if error is not None:
        return error
    limit, offset, error = _parse_limit_offset(payload)
    if error is not None:
        return error
    department_ids, error = _parse_optional_department_ids(payload)
    if error is not None:
        return error
    include_sub_departments = _parse_bool(payload.get("includeSubDepartments"))
    include_department_path = _parse_bool(payload.get("includeDepartmentPath"))

    departments_by_id, children_by_parent = _load_department_context()
    scope_department_ids = _department_scope_ids(
        department_ids,
        departments_by_id,
        children_by_parent,
        include_sub_departments=include_sub_departments,
    )

    queryset = Department.objects.filter(dept_id__in=departments_by_id).order_by("dept_id")
    if scope_department_ids is not None:
        queryset = queryset.filter(dept_id__in=scope_department_ids)
    use_python_keyword_filter = bool(keyword and is_pinyin_initial_keyword(keyword))
    if keyword and not use_python_keyword_filter:
        keyword_filter = Q(name__icontains=keyword)
        try:
            keyword_filter |= Q(dept_id=int(keyword))
        except (TypeError, ValueError):
            pass
        queryset = queryset.filter(keyword_filter)

    if use_python_keyword_filter:
        matched_departments = [department for department in queryset if department_matches_keyword(department, keyword)]
        total = len(matched_departments)
        departments = matched_departments[offset : offset + limit]
    else:
        total = queryset.count()
        departments = list(queryset[offset : offset + limit])
    items = [
        _serialize_department_with_path(
            department,
            departments_by_id,
            include_department_path=include_department_path,
        )
        for department in departments
    ]
    return JsonResponse(
        {
            "ok": True,
            **_response_meta(
                include_department_path=include_department_path,
                include_sub_departments=include_sub_departments if department_ids is not None else None,
            ),
            "keyword": keyword,
            "limit": limit,
            "offset": offset,
            "departmentIds": department_ids or [],
            "scopeDepartmentIds": scope_department_ids or [],
            "total": total,
            "count": len(items),
            "items": items,
        }
    )


@csrf_exempt
@require_POST
def internal_users_departments(request):
    payload, error = _internal_payload(request)
    if error is not None:
        return error

    user_ids, error = _parse_user_ids(payload)
    if error is not None:
        return error
    status_key, status_value, account_key, account_value, error = _parse_employee_filters(payload)
    if error is not None:
        return error
    include_department_path = _parse_bool(payload.get("includeDepartmentPath"))
    include_employee_profiles = _parse_bool(payload.get("includeEmployeeProfiles"))

    departments_by_id, _children_by_parent = _load_department_context()
    unique_user_ids = _unique_ordered(user_ids)
    found_user_ids = set(
        Employee.objects.filter(
            identity_source=Employee.IDENTITY_DINGTALK,
            user_id__in=unique_user_ids,
        ).values_list("user_id", flat=True)
    )
    matched_employee_profiles = _load_employee_profile_map(
        unique_user_ids,
        departments_by_id,
        status=status_value,
        account_status=account_value,
        include_departments=True,
        include_department_path=include_department_path,
    )
    departments_by_user_id = {
        user_id: [department for department in departments if department.dept_id in departments_by_id]
        for user_id, departments in get_employee_departments_map(unique_user_ids).items()
    }

    items = []
    for user_id in user_ids:
        matched_filters = user_id in matched_employee_profiles
        departments = departments_by_user_id.get(user_id, []) if matched_filters else []
        item = {
            "userId": user_id,
            "found": user_id in found_user_ids,
            "matchesFilters": matched_filters,
            "departmentIds": [department.dept_id for department in departments],
            "departments": [
                _serialize_department_with_path(
                    department,
                    departments_by_id,
                    include_department_path=include_department_path,
                )
                for department in departments
            ],
        }
        if include_employee_profiles:
            item["employee"] = matched_employee_profiles.get(user_id)
        items.append(item)

    return JsonResponse(
        {
            "ok": True,
            **_response_meta(
                status_key=status_key,
                account_status_key=account_key,
                include_department_path=include_department_path,
            ),
            "count": len(items),
            "items": items,
        }
    )


@csrf_exempt
@require_POST
def internal_users_leader_chain(request):
    payload, error = _internal_payload(request)
    if error is not None:
        return error

    input_items, error = _parse_user_department_items(payload)
    if error is not None:
        return error
    max_depth, error = _parse_max_depth(payload.get("maxDepth"))
    if error is not None:
        return error
    status_key, status_value, account_key, account_value, error = _parse_employee_filters(payload)
    if error is not None:
        return error
    include_department_path = _parse_bool(payload.get("includeDepartmentPath"))

    departments_by_id, _children_by_parent = _load_department_context()
    user_ids = [item["userId"] for item in input_items]
    department_ids = [item["departmentId"] for item in input_items]
    found_user_ids = set(
        Employee.objects.filter(
            identity_source=Employee.IDENTITY_DINGTALK,
            user_id__in=_unique_ordered(user_ids),
        ).values_list("user_id", flat=True)
    )
    memberships = _membership_pairs(user_ids, department_ids)

    manager_user_ids: list[str] = []
    chain_by_input_index: dict[int, list[Department]] = {}
    for index, item in enumerate(input_items):
        if (item["userId"], item["departmentId"]) not in memberships:
            chain_by_input_index[index] = []
            continue
        chain = _department_chain_to_root(item["departmentId"], departments_by_id, max_depth=max_depth)
        chain_by_input_index[index] = chain
        for department in chain:
            manager_user_ids.extend(_department_manager_user_ids(department))

    manager_profiles = _load_employee_profile_map(
        manager_user_ids,
        departments_by_id,
        status=status_value,
        account_status=account_value,
        include_departments=True,
        include_department_path=include_department_path,
    )

    items = []
    for index, input_item in enumerate(input_items):
        user_id = input_item["userId"]
        department_id = input_item["departmentId"]
        chain = chain_by_input_index.get(index, [])
        levels = []
        for level, department in enumerate(chain, start=1):
            department_manager_user_ids = _department_manager_user_ids(department)
            managers = [
                manager_profiles[manager_user_id]
                for manager_user_id in department_manager_user_ids
                if manager_user_id in manager_profiles
            ]
            manager_user_id = department_manager_user_ids[0] if department_manager_user_ids else ""
            levels.append(
                {
                    "level": level,
                    "department": _serialize_department_with_path(
                        department,
                        departments_by_id,
                        include_department_path=include_department_path,
                    ),
                    "managerUserId": manager_user_id,
                    "manager": manager_profiles.get(manager_user_id),
                    "managerUserIds": department_manager_user_ids,
                    "managers": managers,
                    "isSelf": user_id in department_manager_user_ids,
                }
            )
        items.append(
            {
                "userId": user_id,
                "departmentId": department_id,
                "found": user_id in found_user_ids,
                "departmentFound": department_id in departments_by_id,
                "validMembership": (user_id, department_id) in memberships,
                "count": len(levels),
                "items": levels,
            }
        )

    return JsonResponse(
        {
            "ok": True,
            **_response_meta(
                status_key=status_key,
                account_status_key=account_key,
                include_department_path=include_department_path,
                max_depth=max_depth,
            ),
            "count": len(items),
            "items": items,
        }
    )


@csrf_exempt
@require_POST
def internal_users_colleagues(request):
    payload, error = _internal_payload(request)
    if error is not None:
        return error

    input_items, error = _parse_user_department_items(payload)
    if error is not None:
        return error
    status_key, status_value, account_key, account_value, error = _parse_employee_filters(payload)
    if error is not None:
        return error
    include_self = _parse_bool(payload.get("includeSelf"), default=True)
    include_department_path = _parse_bool(payload.get("includeDepartmentPath"))
    include_departments = _parse_bool(payload.get("includeDepartments"), default=include_department_path)

    departments_by_id, _children_by_parent = _load_department_context()
    user_ids = [item["userId"] for item in input_items]
    department_ids = [item["departmentId"] for item in input_items]
    found_user_ids = set(
        Employee.objects.filter(
            identity_source=Employee.IDENTITY_DINGTALK,
            user_id__in=_unique_ordered(user_ids),
        ).values_list("user_id", flat=True)
    )
    memberships = _membership_pairs(user_ids, department_ids)
    members_by_department_id = _department_members_map(department_ids)
    all_member_user_ids = [
        user_id
        for member_user_ids in members_by_department_id.values()
        for user_id in member_user_ids
    ]
    employee_profiles = _load_employee_profile_map(
        all_member_user_ids,
        departments_by_id,
        status=status_value,
        account_status=account_value,
        include_departments=include_departments,
        include_department_path=include_department_path,
    )

    items = []
    for input_item in input_items:
        user_id = input_item["userId"]
        department_id = input_item["departmentId"]
        valid_membership = (user_id, department_id) in memberships
        colleague_profiles = []
        if valid_membership:
            for colleague_user_id in sorted(members_by_department_id.get(department_id, [])):
                if not include_self and colleague_user_id == user_id:
                    continue
                profile = employee_profiles.get(colleague_user_id)
                if profile is not None:
                    colleague_profiles.append(profile)
        items.append(
            {
                "userId": user_id,
                "departmentId": department_id,
                "found": user_id in found_user_ids,
                "departmentFound": department_id in departments_by_id,
                "validMembership": valid_membership,
                "includeSelf": include_self,
                "count": len(colleague_profiles),
                "items": colleague_profiles,
            }
        )

    return JsonResponse(
        {
            "ok": True,
            **_response_meta(
                status_key=status_key,
                account_status_key=account_key,
                include_department_path=include_department_path,
            ),
            "count": len(items),
            "items": items,
        }
    )


@csrf_exempt
@require_POST
def internal_users_managed_departments(request):
    payload, error = _internal_payload(request)
    if error is not None:
        return error

    user_ids, error = _parse_user_ids(payload)
    if error is not None:
        return error
    include_sub_departments = _parse_bool(payload.get("includeSubDepartments"))
    include_department_path = _parse_bool(payload.get("includeDepartmentPath"))

    departments_by_id, children_by_parent = _load_department_context()
    direct_by_manager_id = _managed_departments_by_user_id(user_ids)

    found_user_ids = set(
        Employee.objects.filter(
            identity_source=Employee.IDENTITY_DINGTALK,
            user_id__in=_unique_ordered(user_ids),
        ).values_list("user_id", flat=True)
    )
    items = []
    for user_id in user_ids:
        direct_departments = direct_by_manager_id.get(user_id, [])
        direct_department_ids = [department.dept_id for department in direct_departments]
        department_ids = list(direct_department_ids)
        if include_sub_departments:
            for department in direct_departments:
                department_ids.extend(
                    _collect_subtree_department_ids(
                        department.dept_id,
                        children_by_parent,
                        include_self=False,
                    )
                )
        department_ids = _unique_ordered(department_ids)
        departments = [departments_by_id[dept_id] for dept_id in department_ids if dept_id in departments_by_id]
        items.append(
            {
                "userId": user_id,
                "found": user_id in found_user_ids,
                "directDepartmentIds": direct_department_ids,
                "directDepartments": [
                    _serialize_department_with_path(
                        department,
                        departments_by_id,
                        include_department_path=include_department_path,
                    )
                    for department in direct_departments
                ],
                "departmentIds": department_ids,
                "departments": [
                    _serialize_department_with_path(
                        department,
                        departments_by_id,
                        include_department_path=include_department_path,
                    )
                    for department in departments
                ],
            }
        )

    return JsonResponse(
        {
            "ok": True,
            **_response_meta(
                include_department_path=include_department_path,
                include_sub_departments=include_sub_departments,
            ),
            "count": len(items),
            "items": items,
        }
    )


@csrf_exempt
@require_POST
def internal_users_managed_employees(request):
    payload, error = _internal_payload(request)
    if error is not None:
        return error

    user_ids, error = _parse_user_ids(payload)
    if error is not None:
        return error
    status_key, status_value, account_key, account_value, error = _parse_employee_filters(payload)
    if error is not None:
        return error
    include_sub_departments = _parse_bool(payload.get("includeSubDepartments"))
    include_department_path = _parse_bool(payload.get("includeDepartmentPath"))
    include_departments = _parse_bool(payload.get("includeDepartments"), default=include_department_path)

    departments_by_id, children_by_parent = _load_department_context()
    direct_by_manager_id = _managed_departments_by_user_id(user_ids)

    found_user_ids = set(
        Employee.objects.filter(
            identity_source=Employee.IDENTITY_DINGTALK,
            user_id__in=_unique_ordered(user_ids),
        ).values_list("user_id", flat=True)
    )
    items = []
    for user_id in user_ids:
        direct_departments = direct_by_manager_id.get(user_id, [])
        groups = []
        unique_profiles_by_id: dict[str, dict] = {}
        for department in direct_departments:
            scope_department_ids = (
                _collect_subtree_department_ids(
                    department.dept_id,
                    children_by_parent,
                    include_self=True,
                )
                if include_sub_departments
                else [department.dept_id]
            )
            employees = _employees_for_department_ids(
                scope_department_ids,
                departments_by_id,
                status=status_value,
                account_status=account_value,
                include_departments=include_departments,
                include_department_path=include_department_path,
            )
            for employee in employees:
                unique_profiles_by_id[employee["userId"]] = employee
            groups.append(
                {
                    "departmentId": department.dept_id,
                    "department": _serialize_department_with_path(
                        department,
                        departments_by_id,
                        include_department_path=include_department_path,
                    ),
                    "scopeDepartmentIds": scope_department_ids,
                    "count": len(employees),
                    "employees": employees,
                }
            )
        unique_employees = [unique_profiles_by_id[user_id] for user_id in sorted(unique_profiles_by_id)]
        items.append(
            {
                "userId": user_id,
                "found": user_id in found_user_ids,
                "directDepartmentIds": [department.dept_id for department in direct_departments],
                "groups": groups,
                "uniqueEmployeeCount": len(unique_employees),
                "uniqueEmployees": unique_employees,
            }
        )

    return JsonResponse(
        {
            "ok": True,
            **_response_meta(
                status_key=status_key,
                account_status_key=account_key,
                include_department_path=include_department_path,
                include_sub_departments=include_sub_departments,
            ),
            "count": len(items),
            "items": items,
        }
    )


@csrf_exempt
@require_POST
def internal_departments_employees(request):
    payload, error = _internal_payload(request)
    if error is not None:
        return error

    department_ids, error = _parse_department_ids(payload)
    if error is not None:
        return error
    status_key, status_value, account_key, account_value, error = _parse_employee_filters(payload)
    if error is not None:
        return error
    include_sub_departments = _parse_bool(payload.get("includeSubDepartments"))
    include_department_path = _parse_bool(payload.get("includeDepartmentPath"))
    include_departments = _parse_bool(payload.get("includeDepartments"), default=include_department_path)

    departments_by_id, children_by_parent = _load_department_context()
    items = []
    for department_id in department_ids:
        department = departments_by_id.get(department_id)
        if department is None:
            items.append(
                {
                    "departmentId": department_id,
                    "found": False,
                    "department": None,
                    "scopeDepartmentIds": [],
                    "count": 0,
                    "items": [],
                }
            )
            continue
        scope_department_ids = (
            _collect_subtree_department_ids(department.dept_id, children_by_parent, include_self=True)
            if include_sub_departments
            else [department.dept_id]
        )
        employees = _employees_for_department_ids(
            scope_department_ids,
            departments_by_id,
            status=status_value,
            account_status=account_value,
            include_departments=include_departments,
            include_department_path=include_department_path,
        )
        items.append(
            {
                "departmentId": department_id,
                "found": True,
                "department": _serialize_department_with_path(
                    department,
                    departments_by_id,
                    include_department_path=include_department_path,
                ),
                "scopeDepartmentIds": scope_department_ids,
                "count": len(employees),
                "items": employees,
            }
        )

    return JsonResponse(
        {
            "ok": True,
            **_response_meta(
                status_key=status_key,
                account_status_key=account_key,
                include_department_path=include_department_path,
                include_sub_departments=include_sub_departments,
            ),
            "count": len(items),
            "items": items,
        }
    )


@csrf_exempt
@require_POST
def internal_departments_managers(request):
    payload, error = _internal_payload(request)
    if error is not None:
        return error

    department_ids, error = _parse_department_ids(payload)
    if error is not None:
        return error
    status_key, status_value, account_key, account_value, error = _parse_employee_filters(payload)
    if error is not None:
        return error
    include_department_path = _parse_bool(payload.get("includeDepartmentPath"))

    departments_by_id, _children_by_parent = _load_department_context()
    manager_user_ids = [
        manager_user_id
        for department_id in _unique_ordered(department_ids)
        if department_id in departments_by_id
        for manager_user_id in _department_manager_user_ids(departments_by_id[department_id])
    ]
    manager_profiles = _load_employee_profile_map(
        manager_user_ids,
        departments_by_id,
        status=status_value,
        account_status=account_value,
        include_departments=True,
        include_department_path=include_department_path,
    )

    items = []
    for department_id in department_ids:
        department = departments_by_id.get(department_id)
        if department is None:
            items.append(
                {
                    "departmentId": department_id,
                    "found": False,
                    "department": None,
                    "managerUserId": "",
                    "manager": None,
                    "managerUserIds": [],
                    "managers": [],
                }
            )
            continue
        department_manager_user_ids = _department_manager_user_ids(department)
        manager_user_id = department_manager_user_ids[0] if department_manager_user_ids else ""
        items.append(
            {
                "departmentId": department_id,
                "found": True,
                "department": _serialize_department_with_path(
                    department,
                    departments_by_id,
                    include_department_path=include_department_path,
                ),
                "managerUserId": manager_user_id,
                "manager": manager_profiles.get(manager_user_id),
                "managerUserIds": department_manager_user_ids,
                "managers": [
                    manager_profiles[user_id]
                    for user_id in department_manager_user_ids
                    if user_id in manager_profiles
                ],
            }
        )

    return JsonResponse(
        {
            "ok": True,
            **_response_meta(
                status_key=status_key,
                account_status_key=account_key,
                include_department_path=include_department_path,
            ),
            "count": len(items),
            "items": items,
        }
    )


@csrf_exempt
@require_POST
def internal_departments_children(request):
    payload, error = _internal_payload(request)
    if error is not None:
        return error

    department_ids, error = _parse_department_ids(payload)
    if error is not None:
        return error
    include_sub_departments = _parse_bool(payload.get("includeSubDepartments"))
    include_department_path = _parse_bool(payload.get("includeDepartmentPath"))

    departments_by_id, children_by_parent = _load_department_context()
    items = []
    for department_id in department_ids:
        department = departments_by_id.get(department_id)
        if department is None:
            items.append(
                {
                    "departmentId": department_id,
                    "found": False,
                    "department": None,
                    "childDepartmentIds": [],
                    "children": [],
                }
            )
            continue
        child_ids = (
            _collect_subtree_department_ids(department_id, children_by_parent, include_self=False)
            if include_sub_departments
            else [child.dept_id for child in children_by_parent.get(department_id, [])]
        )
        children = [departments_by_id[child_id] for child_id in child_ids if child_id in departments_by_id]
        items.append(
            {
                "departmentId": department_id,
                "found": True,
                "department": _serialize_department_with_path(
                    department,
                    departments_by_id,
                    include_department_path=include_department_path,
                ),
                "childDepartmentIds": child_ids,
                "children": [
                    _serialize_department_with_path(
                        child,
                        departments_by_id,
                        include_department_path=include_department_path,
                    )
                    for child in children
                ],
            }
        )

    return JsonResponse(
        {
            "ok": True,
            **_response_meta(
                include_department_path=include_department_path,
                include_sub_departments=include_sub_departments,
            ),
            "count": len(items),
            "items": items,
        }
    )


@csrf_exempt
@require_POST
def internal_departments_ancestor_chain(request):
    payload, error = _internal_payload(request)
    if error is not None:
        return error

    department_ids, error = _parse_department_ids(payload)
    if error is not None:
        return error
    max_depth, error = _parse_max_depth(payload.get("maxDepth"))
    if error is not None:
        return error
    include_department_path = _parse_bool(payload.get("includeDepartmentPath"))

    departments_by_id, _children_by_parent = _load_department_context()
    items = []
    for department_id in department_ids:
        department = departments_by_id.get(department_id)
        if department is None:
            items.append(
                {
                    "departmentId": department_id,
                    "found": False,
                    "department": None,
                    "count": 0,
                    "items": [],
                }
            )
            continue
        chain = _department_chain_to_root(department_id, departments_by_id)
        chain = chain[1:]
        if max_depth is not None:
            chain = chain[:max_depth]
        items.append(
            {
                "departmentId": department_id,
                "found": True,
                "department": _serialize_department_with_path(
                    department,
                    departments_by_id,
                    include_department_path=include_department_path,
                ),
                "count": len(chain),
                "items": [
                    {
                        "level": level,
                        "department": _serialize_department_with_path(
                            chain_department,
                            departments_by_id,
                            include_department_path=include_department_path,
                        ),
                    }
                    for level, chain_department in enumerate(chain, start=1)
                ],
            }
        )

    return JsonResponse(
        {
            "ok": True,
            **_response_meta(
                include_department_path=include_department_path,
                max_depth=max_depth,
            ),
            "count": len(items),
            "items": items,
        }
    )
