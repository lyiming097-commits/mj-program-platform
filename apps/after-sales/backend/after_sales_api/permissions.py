from __future__ import annotations

from typing import Iterable

from django.db import transaction

from .models import AppPermissionRule
from .org_client import get_auth_user_department_scope


APP_PERMISSION_ADMIN = AppPermissionRule.PERMISSION_ADMIN
APP_PERMISSION_SALES = AppPermissionRule.PERMISSION_SALES
APP_PERMISSION_SERVICE = AppPermissionRule.PERMISSION_SERVICE
APP_PERMISSION_LABELS = {
    APP_PERMISSION_ADMIN: "系统管理员",
    APP_PERMISSION_SERVICE: "服务管理员",
    APP_PERMISSION_SALES: "业务员",
}
APP_SCOPE_DEPARTMENT = AppPermissionRule.SCOPE_DEPARTMENT
APP_SCOPE_DEPARTMENT_WITH_SUB = AppPermissionRule.SCOPE_DEPARTMENT_WITH_SUB
APP_SCOPE_EMPLOYEE = AppPermissionRule.SCOPE_EMPLOYEE
APP_SCOPE_EXCLUDED_EMPLOYEE = AppPermissionRule.SCOPE_EXCLUDED_EMPLOYEE
APP_SCOPE_LABELS = {
    APP_SCOPE_DEPARTMENT: "部门",
    APP_SCOPE_DEPARTMENT_WITH_SUB: "部门及下级",
    APP_SCOPE_EMPLOYEE: "成员",
    APP_SCOPE_EXCLUDED_EMPLOYEE: "排除成员",
}
APP_PERMISSION_SCOPES = {
    APP_SCOPE_DEPARTMENT,
    APP_SCOPE_DEPARTMENT_WITH_SUB,
    APP_SCOPE_EMPLOYEE,
    APP_SCOPE_EXCLUDED_EMPLOYEE,
}

MAX_PERMISSION_RULES = 2000
MAX_TARGET_ID_LENGTH = 64
MAX_TARGET_NAME_LENGTH = 255
MAX_ACTOR_ID_LENGTH = 64
MAX_SORT_ORDER = 2_147_483_647


def _text(value) -> str:
    return str(value or "").strip()


def _normalize_sort_order(value, fallback: int) -> int:
    if value is None or value == "":
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("权限排序值必须是整数") from exc
    if parsed < 0 or parsed > MAX_SORT_ORDER:
        raise ValueError(f"权限排序值必须在 0 到 {MAX_SORT_ORDER} 之间")
    return parsed


def _normalize_permission_items(items: Iterable[dict]) -> list[dict]:
    if not isinstance(items, list):
        raise ValueError("权限数据格式错误")
    if len(items) > MAX_PERMISSION_RULES:
        raise ValueError(f"权限规则不能超过 {MAX_PERMISSION_RULES} 条")

    normalized: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"第{index + 1}条权限规则格式错误")
        permission = _text(item.get("permission"))
        scope_type = _text(item.get("scopeType") or item.get("scope_type"))
        target_id = _text(item.get("targetId") or item.get("target_id"))
        submitted_name = _text(item.get("targetName") or item.get("target_name"))

        if permission not in APP_PERMISSION_LABELS:
            raise ValueError(f"第{index + 1}条权限规则的权限类型无效")
        if scope_type not in APP_PERMISSION_SCOPES:
            raise ValueError(f"第{index + 1}条权限规则的范围类型无效")
        if not target_id:
            raise ValueError(f"第{index + 1}条权限规则缺少目标")
        if len(target_id) > MAX_TARGET_ID_LENGTH:
            raise ValueError(f"第{index + 1}条权限规则的目标ID过长")
        if len(submitted_name) > MAX_TARGET_NAME_LENGTH:
            raise ValueError(f"第{index + 1}条权限规则的目标名称过长")

        key = (permission, scope_type, target_id)
        if key in seen:
            raise ValueError(f"第{index + 1}条权限规则重复")
        seen.add(key)
        normalized.append({
            "permission": permission,
            "scope_type": scope_type,
            "target_id": target_id,
            "target_name": submitted_name,
            "sort_order": _normalize_sort_order(
                item.get("sortOrder") if item.get("sortOrder") is not None else item.get("sort_order"),
                index,
            ),
        })
    return normalized


def _department_directory(departments: Iterable[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in departments:
        if not isinstance(row, dict):
            continue
        target_id = _text(row.get("deptId") or row.get("id"))
        if target_id:
            result[target_id] = row
    return result


def _employee_is_active(employee: dict) -> bool:
    status = _text(employee.get("status")).lower()
    account_status = _text(employee.get("accountStatus") or employee.get("account_status")).lower()
    return status in {"active", "在职"} and account_status in {"enabled", "启用"}


def _employee_directory(employees: Iterable[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in employees:
        if not isinstance(row, dict) or not _employee_is_active(row):
            continue
        target_id = _text(row.get("userId") or row.get("id"))
        if target_id:
            result[target_id] = row
    return result


def _canonical_name(row: dict, *, fallback: str) -> str:
    name = _text(row.get("rawName") or row.get("name")) or fallback
    if len(name) > MAX_TARGET_NAME_LENGTH:
        raise ValueError(f"组织架构目标名称过长：{fallback}")
    return name


def _validate_permission_targets(
    items: list[dict],
    *,
    departments: Iterable[dict],
    employees: Iterable[dict],
) -> None:
    department_by_id = _department_directory(departments)
    employee_by_id = _employee_directory(employees)

    for item in items:
        target_id = item["target_id"]
        if item["scope_type"] in {APP_SCOPE_DEPARTMENT, APP_SCOPE_DEPARTMENT_WITH_SUB}:
            try:
                int(target_id)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"权限部门ID不合法：{target_id}") from exc
            department = department_by_id.get(target_id)
            if department is None:
                raise ValueError(f"权限部门不存在：{target_id}")
            item["target_name"] = _canonical_name(department, fallback=target_id)
            continue

        employee = employee_by_id.get(target_id)
        if employee is None:
            raise ValueError(f"权限人员不存在、已离职或账号已停用：{target_id}")
        item["target_name"] = _canonical_name(employee, fallback=target_id)


def serialize_app_permission_rule(rule: AppPermissionRule) -> dict:
    return {
        "id": rule.id,
        "permission": rule.permission,
        "permissionLabel": APP_PERMISSION_LABELS.get(rule.permission, rule.permission),
        "scopeType": rule.scope_type,
        "scopeLabel": APP_SCOPE_LABELS.get(rule.scope_type, rule.scope_type),
        "targetId": rule.target_id,
        "targetName": rule.target_name,
        "sortOrder": rule.sort_order,
        "createdBy": rule.created_by,
        "createdAt": rule.created_at.isoformat() if rule.created_at else "",
        "updatedAt": rule.updated_at.isoformat() if rule.updated_at else "",
    }


def list_app_permission_rules() -> list[dict]:
    return [
        serialize_app_permission_rule(rule)
        for rule in AppPermissionRule.objects.filter(
            permission__in=APP_PERMISSION_LABELS,
            scope_type__in=APP_PERMISSION_SCOPES,
        )
    ]


@transaction.atomic
def replace_app_permission_rules(
    items: list[dict],
    *,
    departments: Iterable[dict],
    employees: Iterable[dict],
    actor_user_id: str = "",
) -> list[dict]:
    normalized_items = _normalize_permission_items(items)
    _validate_permission_targets(
        normalized_items,
        departments=departments,
        employees=employees,
    )
    actor_user_id = _text(actor_user_id)
    if len(actor_user_id) > MAX_ACTOR_ID_LENGTH:
        raise ValueError("操作人ID过长")

    AppPermissionRule.objects.all().delete()
    AppPermissionRule.objects.bulk_create([
        AppPermissionRule(
            permission=item["permission"],
            scope_type=item["scope_type"],
            target_id=item["target_id"],
            target_name=item["target_name"],
            sort_order=item["sort_order"],
            created_by=actor_user_id,
        )
        for item in normalized_items
    ])
    return list_app_permission_rules()


def get_user_app_permissions(user_id: str) -> set[str]:
    normalized_user_id = _text(user_id)
    if not normalized_user_id:
        return set()

    rules = list(
        AppPermissionRule.objects.filter(
            permission__in=APP_PERMISSION_LABELS,
            scope_type__in=APP_PERMISSION_SCOPES,
        ).only("permission", "scope_type", "target_id")
    )
    if not rules:
        return set()

    permissions = set()
    scope = None
    for permission in APP_PERMISSION_LABELS:
        own_rules = [rule for rule in rules if rule.permission == permission]
        if any(rule.scope_type == APP_SCOPE_EXCLUDED_EMPLOYEE and rule.target_id == normalized_user_id
               for rule in own_rules):
            continue
        if any(rule.scope_type == APP_SCOPE_EMPLOYEE and rule.target_id == normalized_user_id
               for rule in own_rules):
            permissions.add(permission)
            continue
        department_rules = [rule for rule in own_rules if rule.scope_type in {
            APP_SCOPE_DEPARTMENT, APP_SCOPE_DEPARTMENT_WITH_SUB,
        }]
        if department_rules and scope is None:
            scope = get_auth_user_department_scope(normalized_user_id)
        if any((rule.scope_type == APP_SCOPE_DEPARTMENT and rule.target_id in scope["directDepartmentIds"])
               or (rule.scope_type == APP_SCOPE_DEPARTMENT_WITH_SUB and rule.target_id in scope["ancestorDepartmentIds"])
               for rule in department_rules):
            permissions.add(permission)
    return permissions


def get_user_app_permission(user_id: str) -> str:
    permissions = get_user_app_permissions(user_id)
    return next((value for value in APP_PERMISSION_LABELS if value in permissions), "")


def get_request_app_permissions(request) -> set[str]:
    # Application grants never turn a WeChat identity into a management user.
    if (getattr(request, "auth_token_claims", {}) or {}).get("chn", "dingtalk") != "dingtalk":
        return set()
    if getattr(request, "auth_can_use_system_admin", False) is True:
        return {APP_PERMISSION_ADMIN}
    if not hasattr(request, "_after_sales_permissions"):
        request._after_sales_permissions = get_user_app_permissions(getattr(request, "auth_user_id", ""))
    return set(request._after_sales_permissions)


def get_request_app_permission(request) -> str:
    permissions = get_request_app_permissions(request)
    return next((value for value in APP_PERMISSION_LABELS if value in permissions), "")
