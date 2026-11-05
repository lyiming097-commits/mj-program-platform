from __future__ import annotations

from typing import Iterable

from django.db import transaction

from identity_api.auth.org_client import (
    AuthOrgClientError,
    build_auth_department_tree,
    get_auth_organization_snapshot,
)
from identity_api.models import Department, Employee, DepartmentEmployee
from identity_api.org.queries import (
    get_request_permission_user_id,
)

from .models import CableMallPermissionRule
from .org_sync import refresh_auth_organization_snapshot, sync_auth_organization_snapshot


CABLE_MALL_PERMISSION_ADMIN = CableMallPermissionRule.PERMISSION_ADMIN
CABLE_MALL_PERMISSION_USER = CableMallPermissionRule.PERMISSION_USER
CABLE_MALL_PERMISSION_LABELS = {
    CABLE_MALL_PERMISSION_ADMIN: "线材商城管理员",
    CABLE_MALL_PERMISSION_USER: "线材商城普通用户",
}
CABLE_MALL_SCOPE_DEPARTMENT = CableMallPermissionRule.SCOPE_DEPARTMENT
CABLE_MALL_SCOPE_DEPARTMENT_WITH_SUB = CableMallPermissionRule.SCOPE_DEPARTMENT_WITH_SUB
CABLE_MALL_SCOPE_EMPLOYEE = CableMallPermissionRule.SCOPE_EMPLOYEE
CABLE_MALL_SCOPE_EXCLUDED_EMPLOYEE = CableMallPermissionRule.SCOPE_EXCLUDED_EMPLOYEE
CABLE_MALL_SCOPE_LABELS = {
    CABLE_MALL_SCOPE_DEPARTMENT: "部门",
    CABLE_MALL_SCOPE_DEPARTMENT_WITH_SUB: "部门（含下级）",
    CABLE_MALL_SCOPE_EMPLOYEE: "成员",
    CABLE_MALL_SCOPE_EXCLUDED_EMPLOYEE: "排除成员",
}
CABLE_MALL_PERMISSION_RANK = {
    "": 0,
    CABLE_MALL_PERMISSION_USER: 1,
    CABLE_MALL_PERMISSION_ADMIN: 2,
}


def _normalize_id(value) -> str:
    return str(value or "").strip()


def _valid_permission(value: str) -> bool:
    return value in {CABLE_MALL_PERMISSION_ADMIN, CABLE_MALL_PERMISSION_USER}


def _valid_scope(value: str) -> bool:
    return value in {
        CABLE_MALL_SCOPE_DEPARTMENT,
        CABLE_MALL_SCOPE_DEPARTMENT_WITH_SUB,
        CABLE_MALL_SCOPE_EMPLOYEE,
        CABLE_MALL_SCOPE_EXCLUDED_EMPLOYEE,
    }


def _max_permission(left: str, right: str) -> str:
    return left if CABLE_MALL_PERMISSION_RANK.get(left, 0) >= CABLE_MALL_PERMISSION_RANK.get(right, 0) else right


def _rule_matches_user(
    rule: CableMallPermissionRule,
    user_id: str,
    *,
    user_department_ids: set[int],
    user_department_ancestor_ids: set[int],
) -> bool:
    target_id = _normalize_id(rule.target_id)
    if not target_id:
        return False
    if rule.scope_type == CABLE_MALL_SCOPE_EMPLOYEE:
        return target_id == user_id
    if rule.scope_type == CABLE_MALL_SCOPE_DEPARTMENT:
        try:
            return int(target_id) in user_department_ids
        except (TypeError, ValueError):
            return False
    if rule.scope_type == CABLE_MALL_SCOPE_DEPARTMENT_WITH_SUB:
        try:
            return int(target_id) in user_department_ancestor_ids
        except (TypeError, ValueError):
            return False
    return False


def _resolve_target_name(scope_type: str, target_id: str, fallback: str = "") -> str:
    fallback = _normalize_id(fallback)
    if scope_type in {CABLE_MALL_SCOPE_DEPARTMENT, CABLE_MALL_SCOPE_DEPARTMENT_WITH_SUB}:
        try:
            department = Department.objects.filter(dept_id=int(target_id)).first()
        except (TypeError, ValueError):
            department = None
        return str(getattr(department, "name", "") or fallback or target_id)
    if scope_type in {CABLE_MALL_SCOPE_EMPLOYEE, CABLE_MALL_SCOPE_EXCLUDED_EMPLOYEE}:
        employee = Employee.objects.filter(user_id=target_id).first()
        return str(getattr(employee, "name", "") or fallback or target_id)
    return fallback or target_id


def _normalize_sort_order(value, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(parsed, 0)


def _normalize_permission_items(items: Iterable[dict]) -> list[dict]:
    normalized = []
    seen = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"第{index + 1}条权限规则格式错误")
        permission = _normalize_id(item.get("permission"))
        scope_type = _normalize_id(item.get("scopeType") or item.get("scope_type"))
        target_id = _normalize_id(item.get("targetId") or item.get("target_id"))
        if not (_valid_permission(permission) and _valid_scope(scope_type) and target_id):
            raise ValueError(f"第{index + 1}条权限规则缺少有效的权限、范围或目标")
        key = (permission, scope_type, target_id)
        if key in seen:
            raise ValueError(f"第{index + 1}条权限规则重复")
        seen.add(key)
        normalized.append(
            {
                "permission": permission,
                "scope_type": scope_type,
                "target_id": target_id,
                "target_name": _resolve_target_name(
                    scope_type,
                    target_id,
                    item.get("targetName") or item.get("target_name") or "",
                ),
                "sort_order": _normalize_sort_order(
                    item.get("sortOrder") if item.get("sortOrder") is not None else item.get("sort_order"),
                    index,
                ),
            }
        )
    return normalized


def _validate_permission_targets(items: list[dict]) -> None:
    department_target_ids: set[int] = set()
    for item in items:
        if item["scope_type"] not in {CABLE_MALL_SCOPE_DEPARTMENT, CABLE_MALL_SCOPE_DEPARTMENT_WITH_SUB}:
            continue
        try:
            department_target_ids.add(int(item["target_id"]))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"权限部门ID不合法：{item['target_id']}") from exc
    employee_target_ids = {
        item["target_id"]
        for item in items
        if item["scope_type"] in {CABLE_MALL_SCOPE_EMPLOYEE, CABLE_MALL_SCOPE_EXCLUDED_EMPLOYEE}
    }
    departments = {
        int(department.dept_id): department
        for department in Department.objects.filter(dept_id__in=department_target_ids)
    }
    employees = {
        employee.user_id: employee
        for employee in Employee.objects.filter(
            user_id__in=employee_target_ids,
            status=Employee.STATUS_ACTIVE,
        )
    }
    missing_department_ids = department_target_ids - set(departments)
    if missing_department_ids:
        raise ValueError(f"权限部门不存在：{min(missing_department_ids)}")
    missing_employee_ids = employee_target_ids - set(employees)
    if missing_employee_ids:
        raise ValueError(f"权限人员不存在或已离职：{sorted(missing_employee_ids)[0]}")
    for item in items:
        if item["scope_type"] in {CABLE_MALL_SCOPE_DEPARTMENT, CABLE_MALL_SCOPE_DEPARTMENT_WITH_SUB}:
            item["target_name"] = departments[int(item["target_id"])].name
        elif item["scope_type"] in {CABLE_MALL_SCOPE_EMPLOYEE, CABLE_MALL_SCOPE_EXCLUDED_EMPLOYEE}:
            item["target_name"] = employees[item["target_id"]].name


def serialize_cable_mall_permission_rule(rule: CableMallPermissionRule) -> dict:
    return {
        "id": rule.id,
        "permission": rule.permission,
        "permissionLabel": CABLE_MALL_PERMISSION_LABELS.get(rule.permission, rule.permission),
        "scopeType": rule.scope_type,
        "scopeLabel": CABLE_MALL_SCOPE_LABELS.get(rule.scope_type, rule.scope_type),
        "targetId": rule.target_id,
        "targetName": rule.target_name,
        "sortOrder": rule.sort_order,
        "createdBy": rule.created_by,
        "createdAt": rule.created_at.isoformat() if rule.created_at else "",
        "updatedAt": rule.updated_at.isoformat() if rule.updated_at else "",
    }


def list_cable_mall_permission_rules() -> list[dict]:
    return [
        serialize_cable_mall_permission_rule(rule)
        for rule in CableMallPermissionRule.objects.filter(
            scope_type__in=[
                CABLE_MALL_SCOPE_DEPARTMENT,
                CABLE_MALL_SCOPE_DEPARTMENT_WITH_SUB,
                CABLE_MALL_SCOPE_EMPLOYEE,
                CABLE_MALL_SCOPE_EXCLUDED_EMPLOYEE,
            ],
        )
    ]


def replace_cable_mall_permission_rules(items: Iterable[dict], *, actor_user_id: str = "") -> list[dict]:
    normalized_items = _normalize_permission_items(items)
    _validate_permission_targets(normalized_items)
    actor_user_id = _normalize_id(actor_user_id)
    with transaction.atomic():
        CableMallPermissionRule.objects.all().delete()
        CableMallPermissionRule.objects.bulk_create(
            [
                CableMallPermissionRule(
                    permission=item["permission"],
                    scope_type=item["scope_type"],
                    target_id=item["target_id"],
                    target_name=item["target_name"],
                    sort_order=item["sort_order"],
                    created_by=actor_user_id,
                )
                for item in normalized_items
            ],
        )
    return list_cable_mall_permission_rules()


def get_user_cable_mall_scope(user_id: str, *, system_admin_access: bool = False) -> dict:
    normalized_user_id = _normalize_id(user_id)
    valid_rule_scope_types = [
        CABLE_MALL_SCOPE_DEPARTMENT,
        CABLE_MALL_SCOPE_DEPARTMENT_WITH_SUB,
        CABLE_MALL_SCOPE_EMPLOYEE,
        CABLE_MALL_SCOPE_EXCLUDED_EMPLOYEE,
    ]
    has_rules = CableMallPermissionRule.objects.filter(scope_type__in=valid_rule_scope_types).exists()
    if not normalized_user_id:
        return {
            "user_id": "",
            "permission": "",
            "can_access_cable_mall": False,
            "can_manage_cable_mall": False,
            "is_system_admin": False,
            "rules_configured": has_rules,
        }

    if system_admin_access:
        return {
            "user_id": normalized_user_id,
            "permission": CABLE_MALL_PERMISSION_ADMIN,
            "can_access_cable_mall": True,
            "can_manage_cable_mall": True,
            "is_system_admin": True,
            "rules_configured": has_rules,
        }

    permission = ""

    user_department_ids = {
        int(dept_id)
        for dept_id in DepartmentEmployee.objects.filter(employee_id=normalized_user_id)
        .values_list("department_id", flat=True)
    }
    parent_by_department_id = {
        int(dept_id): (int(parent_id) if parent_id is not None else None)
        for dept_id, parent_id in Department.objects.values_list("dept_id", "parent_dept_id")
    }
    user_department_ancestor_ids = set(user_department_ids)
    for department_id in user_department_ids:
        current_id = department_id
        visited: set[int] = set()
        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            user_department_ancestor_ids.add(current_id)
            current_id = parent_by_department_id.get(current_id)

    rules = list(
        CableMallPermissionRule.objects.filter(scope_type__in=valid_rule_scope_types)
        .only("permission", "scope_type", "target_id")
    )
    excluded_permissions = {
        rule.permission
        for rule in rules
        if rule.scope_type == CABLE_MALL_SCOPE_EXCLUDED_EMPLOYEE
        and _normalize_id(rule.target_id) == normalized_user_id
    }
    for rule in rules:
        if rule.scope_type == CABLE_MALL_SCOPE_EXCLUDED_EMPLOYEE or rule.permission in excluded_permissions:
            continue
        if _rule_matches_user(
            rule,
            normalized_user_id,
            user_department_ids=user_department_ids,
            user_department_ancestor_ids=user_department_ancestor_ids,
        ):
            permission = _max_permission(permission, rule.permission)

    can_access = permission in {CABLE_MALL_PERMISSION_ADMIN, CABLE_MALL_PERMISSION_USER}
    can_manage = permission == CABLE_MALL_PERMISSION_ADMIN
    return {
        "user_id": normalized_user_id,
        "permission": permission,
        "can_access_cable_mall": can_access,
        "can_manage_cable_mall": can_manage,
        "is_system_admin": False,
        "rules_configured": has_rules,
    }


def request_cable_mall_scope(request) -> dict:
    if (
        getattr(request, "auth_can_use_system_admin", False) is not True
        and not getattr(request, "_cable_mall_org_refresh_attempted", False)
    ):
        request._cable_mall_org_refresh_attempted = True
        try:
            refresh_auth_organization_snapshot()
        except AuthOrgClientError:
            # Authorization can continue from the last complete local snapshot if Auth is temporarily unavailable.
            pass
    return get_user_cable_mall_scope(
        get_request_permission_user_id(request),
        system_admin_access=getattr(request, "auth_can_use_system_admin", False) is True,
    )


def request_can_access_cable_mall(request) -> bool:
    return bool(request_cable_mall_scope(request)["can_access_cable_mall"])


def request_can_manage_cable_mall(request) -> bool:
    return bool(request_cable_mall_scope(request)["can_manage_cable_mall"])


def cable_mall_permission_directory() -> dict:
    department_rows, all_employees, org_revision = get_auth_organization_snapshot()
    sync_auth_organization_snapshot(
        department_rows,
        all_employees,
        org_revision=org_revision,
    )
    employees = [
        employee
        for employee in all_employees
        if _normalize_id(employee.get("status")) == Employee.STATUS_ACTIVE
    ]
    return {
        "departments": build_auth_department_tree(department_rows),
        "roles": [],
        "employees": employees,
        "directorySource": "auth",
        "orgRevision": org_revision,
    }
