from __future__ import annotations

from collections import defaultdict, deque
import os
import re
from typing import Iterable

from django.db.models import Q

from ..models import Department, DepartmentEmployee, DepartmentManager, Employee

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:  # pragma: no cover - dependency is installed in Docker images.
    Style = None
    lazy_pinyin = None


_UNSET = object()
_PINYIN_KEYWORD_RE = re.compile(r"^[A-Za-z\s'-]+$")


def _load_full_access_user_ids() -> set[str]:
    raw_value = os.getenv("FULL_ACCESS_USER_IDS", "")
    normalized_value = raw_value.replace(";", ",").replace("\n", ",")
    return {
        user_id.strip()
        for user_id in normalized_value.split(",")
        if user_id.strip()
    }


FULL_ACCESS_USER_IDS = _load_full_access_user_ids()


def serialize_department(department: Department) -> dict:
    manager_user_ids = [
        str(user_id or "").strip()
        for user_id in (department.manager_user_ids or [])
        if str(user_id or "").strip()
    ]
    if not manager_user_ids and department.manager_user_id:
        manager_user_ids = [department.manager_user_id]
    return {
        "deptId": department.dept_id,
        "name": department.name,
        "pinyin": pinyin_text(department.name),
        "pinyinInitials": pinyin_initials(department.name),
        "managerUserId": department.manager_user_id,
        "managerUserIds": manager_user_ids,
        "parentDeptId": department.parent_dept_id,
        "updatedAt": department.updated_at.isoformat(),
    }


def is_pinyin_initial_keyword(keyword: str) -> bool:
    return bool(_PINYIN_KEYWORD_RE.fullmatch(str(keyword or "").strip()))


def normalize_pinyin_keyword(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def pinyin_text(value: str) -> str:
    text = str(value or "").strip()
    if not text or lazy_pinyin is None:
        return ""
    parts = lazy_pinyin(text, errors="default")
    return normalize_pinyin_keyword("".join(str(part or "") for part in parts))


def pinyin_initials(value: str) -> str:
    text = str(value or "").strip()
    if not text or lazy_pinyin is None or Style is None:
        return ""
    parts = lazy_pinyin(text, style=Style.FIRST_LETTER, errors="default")
    return "".join(str(part or "").strip()[:1].lower() for part in parts if str(part or "").strip())


def keyword_matches_text(value: str, keyword: str) -> bool:
    normalized_keyword = str(keyword or "").strip().casefold()
    if not normalized_keyword:
        return True

    normalized_value = str(value or "").strip().casefold()
    if normalized_keyword in normalized_value:
        return True

    if is_pinyin_initial_keyword(normalized_keyword):
        compact_keyword = normalize_pinyin_keyword(normalized_keyword)
        return (
            compact_keyword in pinyin_text(normalized_value)
            or compact_keyword in pinyin_initials(normalized_value)
        )

    return False


def employee_matches_keyword(employee: Employee, keyword: str) -> bool:
    return (
        keyword_matches_text(employee.name, keyword)
        or keyword_matches_text(employee.user_id, keyword)
    )


def department_matches_keyword(department: Department, keyword: str) -> bool:
    return (
        keyword_matches_text(department.name, keyword)
        or keyword_matches_text(str(department.dept_id), keyword)
    )


def has_full_access_user_id(user_id: str) -> bool:
    normalized_user_id = str(user_id or "").strip()
    return bool(normalized_user_id and normalized_user_id in FULL_ACCESS_USER_IDS)


def get_request_permission_user_id(request) -> str:
    return str(getattr(request, "auth_user_id", "") or "").strip()


def request_has_full_access_user_id(request) -> bool:
    # Whitelist identity follows the effective user. A proxy session never
    # inherits the actor's whitelist status, but a whitelisted target keeps it.
    return has_full_access_user_id(get_request_permission_user_id(request))


def get_employee_display_name(employee: Employee | None) -> str:
    if employee is None:
        return ""

    raw_name = str(employee.name or "").strip()
    if employee.status != Employee.STATUS_INACTIVE:
        return raw_name

    handover_name = "\u672a\u4ea4\u63a5"
    handover_user_id = str(employee.handover_user_id or "").strip()
    if handover_user_id:
        handover_employee = get_employee_or_none(handover_user_id)
        resolved_handover_name = str(getattr(handover_employee, "name", "") or "").strip()
        if resolved_handover_name:
            handover_name = resolved_handover_name

    if raw_name:
        return f"{raw_name}\uff08{handover_name}\uff09"
    return handover_name


def serialize_employee(employee: Employee) -> dict:
    display_name = get_employee_display_name(employee)
    return {
        "userId": employee.user_id,
        "name": display_name,
        "rawName": employee.name,
        "pinyin": pinyin_text(employee.name),
        "pinyinInitials": pinyin_initials(employee.name),
        "avatarUrl": employee.avatar_url,
        "status": employee.status,
        "accountStatus": employee.account_status,
        "handoverUserId": employee.handover_user_id,
        "createTime": employee.create_time.isoformat() if employee.create_time else "",
        "updatedAt": employee.updated_at.isoformat(),
    }


def serialize_employee_with_departments(employee: Employee, departments: list[Department]) -> dict:
    payload = serialize_employee(employee)
    payload["departments"] = [serialize_department(item) for item in departments]
    return payload


def get_department_or_none(dept_id: int) -> Department | None:
    return Department.objects.filter(dept_id=dept_id).first()


def get_employee_or_none(user_id: str) -> Employee | None:
    return Employee.objects.filter(
        user_id=user_id,
        identity_source=Employee.IDENTITY_DINGTALK,
    ).first()


def get_child_department_ids(parent_dept_id: int | None) -> list[int]:
    return list(
        Department.objects.filter(parent_dept_id=parent_dept_id)
        .order_by("dept_id")
        .values_list("dept_id", flat=True)
    )


def get_subtree_department_ids(root_dept_id: int, *, include_self: bool = True) -> list[int]:
    children_by_parent: dict[int | None, list[int]] = defaultdict(list)
    for dept_id, parent_dept_id in Department.objects.values_list("dept_id", "parent_dept_id"):
        children_by_parent[parent_dept_id].append(dept_id)

    result: list[int] = []
    queue: deque[int] = deque([root_dept_id])
    visited: set[int] = set()

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        if include_self or current != root_dept_id:
            result.append(current)
        for child_id in children_by_parent.get(current, []):
            if child_id not in visited:
                queue.append(child_id)

    return result


def get_departments_by_ids(dept_ids: Iterable[int]) -> list[Department]:
    dept_ids = list(dept_ids)
    if not dept_ids:
        return []
    departments = Department.objects.filter(dept_id__in=dept_ids)
    order_map = {dept_id: index for index, dept_id in enumerate(dept_ids)}
    return sorted(departments, key=lambda item: order_map.get(item.dept_id, 0))


def get_department_manager(department: Department) -> Employee | None:
    if not department.manager_user_id:
        return None
    return get_employee_or_none(department.manager_user_id)


def get_department_managers(department: Department) -> list[Employee]:
    relations = (
        DepartmentManager.objects.filter(department_id=department.dept_id)
        .select_related("employee")
        .order_by("sort_order", "employee_id")
    )
    managers = [relation.employee for relation in relations]
    if managers:
        return managers
    manager = get_department_manager(department)
    return [manager] if manager is not None else []


def get_employee_departments(user_id: str) -> list[Department]:
    department_ids = list(
        DepartmentEmployee.objects.filter(employee_id=user_id)
        .order_by("department_id")
        .values_list("department_id", flat=True)
    )
    return get_departments_by_ids(department_ids)


def get_employee_departments_map(user_ids: Iterable[str]) -> dict[str, list[Department]]:
    normalized_user_ids = [
        str(user_id or "").strip()
        for user_id in user_ids
        if str(user_id or "").strip()
    ]
    departments_by_user_id: dict[str, list[Department]] = defaultdict(list)
    if not normalized_user_ids:
        return departments_by_user_id

    rows = (
        DepartmentEmployee.objects.filter(employee_id__in=normalized_user_ids)
        .select_related("department")
        .order_by("employee_id", "department_id")
    )
    for row in rows:
        departments_by_user_id[row.employee_id].append(row.department)
    return departments_by_user_id


def serialize_employee_profile(
    employee: Employee,
    *,
    include_departments: bool = False,
    departments: list[Department] | None = None,
    handover_employee: Employee | None | object = _UNSET,
) -> dict:
    payload = serialize_employee(employee)
    if employee.handover_user_id:
        if handover_employee is _UNSET:
            handover_employee = get_employee_or_none(employee.handover_user_id)
        payload["handoverEmployee"] = serialize_employee(handover_employee) if handover_employee else None
    else:
        payload["handoverEmployee"] = None
    if include_departments:
        employee_departments = departments if departments is not None else get_employee_departments(employee.user_id)
        payload["departments"] = [serialize_department(item) for item in employee_departments]
    return payload


def serialize_employee_profiles(
    employees: Iterable[Employee],
    *,
    include_departments: bool = False,
) -> list[dict]:
    employee_list = list(employees)
    user_ids = [employee.user_id for employee in employee_list]
    departments_by_user_id = get_employee_departments_map(user_ids) if include_departments else {}

    handover_user_ids = [
        str(employee.handover_user_id or "").strip()
        for employee in employee_list
        if str(employee.handover_user_id or "").strip()
    ]
    handover_employees = (
        Employee.objects.filter(
            identity_source=Employee.IDENTITY_DINGTALK,
        ).in_bulk(handover_user_ids, field_name="user_id")
        if handover_user_ids
        else {}
    )

    return [
        serialize_employee_profile(
            employee,
            include_departments=include_departments,
            departments=departments_by_user_id.get(employee.user_id, []),
            handover_employee=handover_employees.get(employee.handover_user_id),
        )
        for employee in employee_list
    ]


def list_employees(
    *,
    department_ids: Iterable[int] | None = None,
    status: str | None = None,
    keyword: str = "",
) -> list[Employee]:
    queryset = Employee.objects.filter(
        identity_source=Employee.IDENTITY_DINGTALK,
    ).order_by("user_id")

    if department_ids is not None:
        department_ids = list(department_ids)
        if not department_ids:
            return []
        employee_ids = DepartmentEmployee.objects.filter(
            department_id__in=department_ids,
        ).values_list("employee_id", flat=True)
        queryset = queryset.filter(user_id__in=employee_ids).distinct()

    if status in {Employee.STATUS_ACTIVE, Employee.STATUS_INACTIVE}:
        queryset = queryset.filter(status=status)

    keyword = keyword.strip()
    if keyword:
        if is_pinyin_initial_keyword(keyword):
            return [employee for employee in queryset if employee_matches_keyword(employee, keyword)]
        queryset = queryset.filter(Q(name__icontains=keyword) | Q(user_id__icontains=keyword))

    return list(queryset)


def build_department_tree(root_dept_id: int | None = None) -> list[dict]:
    departments = list(Department.objects.all().order_by("dept_id"))
    children_by_parent: dict[int | None, list[Department]] = defaultdict(list)
    for department in departments:
        children_by_parent[department.parent_dept_id].append(department)

    visited: set[int] = set()

    def build_node(department: Department, ancestors: frozenset[int] = frozenset()) -> dict:
        if department.dept_id in ancestors:
            return {**serialize_department(department), "children": [], "hierarchyCycle": True}
        visited.add(department.dept_id)
        next_ancestors = ancestors | {department.dept_id}
        return {
            **serialize_department(department),
            "children": [
                build_node(child, next_ancestors)
                for child in children_by_parent.get(department.dept_id, [])
                if child.dept_id not in next_ancestors
            ],
        }

    if root_dept_id is not None:
        root = next((item for item in departments if item.dept_id == root_dept_id), None)
        return [build_node(root)] if root else []

    tree = [build_node(item) for item in children_by_parent.get(None, [])]
    tree.extend(build_node(item) for item in departments if item.dept_id not in visited)
    return tree
