from __future__ import annotations

import json
from collections import defaultdict, deque

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import (
    Department,
    DepartmentEmployee,
    Employee,
    OrganizationPermissionState,
    PlatformDepartmentState,
    PlatformEnabledDepartment,
)
from .queries import get_request_permission_user_id, request_has_full_access_user_id
from .revision import advance_organization_revision, get_organization_revision, lock_organization_state


STATE_ID = 1
MAX_DEPARTMENTS = 10_000
MAX_PERMISSION_RULES = 2_000
MAX_SORT_ORDER = 2_147_483_647
SCOPE_DEPARTMENT = "department"
SCOPE_DEPARTMENT_WITH_SUB = "departmentSub"
SCOPE_EMPLOYEE = "employee"
SCOPE_EXCLUDED_EMPLOYEE = "excludedEmployee"
SCOPE_TYPES = {
    SCOPE_DEPARTMENT,
    SCOPE_DEPARTMENT_WITH_SUB,
    SCOPE_EMPLOYEE,
    SCOPE_EXCLUDED_EMPLOYEE,
}
DEPARTMENT_SCOPE_TYPES = {SCOPE_DEPARTMENT, SCOPE_DEPARTMENT_WITH_SUB}
SCOPE_LABELS = {
    SCOPE_DEPARTMENT: "部门",
    SCOPE_DEPARTMENT_WITH_SUB: "部门及下级",
    SCOPE_EMPLOYEE: "人员",
    SCOPE_EXCLUDED_EMPLOYEE: "排除人员",
}


class OrganizationAccessError(ValueError):
    def __init__(self, message: str, *, code: str = "INVALID_ORGANIZATION_ACCESS", status: int = 400, **extra):
        super().__init__(message)
        self.code = code
        self.status = status
        self.extra = extra


def _text(value) -> str:
    return str(value or "").strip()


def _parse_json_body(request) -> dict:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OrganizationAccessError("请求JSON格式错误", code="INVALID_JSON") from exc
    if not isinstance(payload, dict):
        raise OrganizationAccessError("请求JSON必须是对象", code="INVALID_JSON")
    return payload


def _error_response(error: OrganizationAccessError) -> JsonResponse:
    return JsonResponse(
        {"ok": False, "code": error.code, "error": str(error), **error.extra},
        status=error.status,
    )


def _expected_revision(raw_value, *, current: int, field_name: str, required_code: str, conflict_code: str) -> None:
    if raw_value in (None, ""):
        raise OrganizationAccessError(
            f"缺少{field_name}，请刷新后重试",
            code=required_code,
            status=400,
            **{field_name: current},
        )
    try:
        expected = int(raw_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise OrganizationAccessError(f"{field_name}必须是整数", code=required_code) from exc
    if expected != current:
        raise OrganizationAccessError(
            "配置已发生变化，请刷新后重试",
            code=conflict_code,
            status=409,
            **{field_name: current},
        )


def get_platform_enabled_department_ids() -> set[int]:
    configured = PlatformDepartmentState.objects.filter(state_id=STATE_ID).values_list("configured", flat=True).first()
    if configured is not True:
        return set(Department.objects.values_list("dept_id", flat=True))
    return set(PlatformEnabledDepartment.objects.values_list("department_id", flat=True))


class _OrganizationDirectory:
    def __init__(self):
        enabled_ids = get_platform_enabled_department_ids()
        self.departments = {
            department.dept_id: department
            for department in Department.objects.filter(dept_id__in=enabled_ids).order_by("dept_id")
        }
        self.children_by_parent: dict[int | None, list[int]] = defaultdict(list)
        for department in self.departments.values():
            parent_id = department.parent_dept_id
            if parent_id not in self.departments:
                parent_id = None
            self.children_by_parent[parent_id].append(department.dept_id)

        employee_ids = DepartmentEmployee.objects.filter(
            department_id__in=self.departments,
        ).values_list("employee_id", flat=True)
        self.employees = {
            employee.user_id: employee
            for employee in Employee.objects.filter(
                user_id__in=employee_ids,
                identity_source=Employee.IDENTITY_DINGTALK,
                status=Employee.STATUS_ACTIVE,
                account_status=Employee.ACCOUNT_ENABLED,
            ).order_by("user_id")
        }
        self.members_by_department: dict[int, set[str]] = defaultdict(set)
        for department_id, employee_id in DepartmentEmployee.objects.filter(
            department_id__in=self.departments,
            employee_id__in=self.employees,
        ).values_list("department_id", "employee_id"):
            self.members_by_department[department_id].add(employee_id)
        self._subtree_cache: dict[int, tuple[int, ...]] = {}

    def subtree_department_ids(self, root_department_id: int) -> tuple[int, ...]:
        cached = self._subtree_cache.get(root_department_id)
        if cached is not None:
            return cached
        result: list[int] = []
        queue: deque[int] = deque([root_department_id])
        visited: set[int] = set()
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if current in self.departments:
                result.append(current)
                queue.extend(self.children_by_parent.get(current, ()))
        resolved = tuple(result)
        self._subtree_cache[root_department_id] = resolved
        return resolved

    def department_member_ids(self, department_id: int, *, include_sub_departments: bool) -> set[str]:
        department_ids = (
            self.subtree_department_ids(department_id)
            if include_sub_departments
            else (department_id,)
        )
        result: set[str] = set()
        for scoped_department_id in department_ids:
            result.update(self.members_by_department.get(scoped_department_id, ()))
        return result


def _permission_allows_user(rules: list[dict], user_id: str) -> bool:
    if any(
        rule.get("scopeType") == SCOPE_EXCLUDED_EMPLOYEE and rule.get("targetId") == user_id
        for rule in rules
    ):
        return False
    if any(
        rule.get("scopeType") == SCOPE_EMPLOYEE and rule.get("targetId") == user_id
        for rule in rules
    ):
        return True

    enabled_ids = get_platform_enabled_department_ids()
    direct_department_ids = set(
        DepartmentEmployee.objects.filter(
            employee_id=user_id,
            department_id__in=enabled_ids,
        ).values_list("department_id", flat=True)
    )
    if not direct_department_ids:
        return False
    if any(
        rule.get("scopeType") == SCOPE_DEPARTMENT
        and str(rule.get("targetId")) in {str(value) for value in direct_department_ids}
        for rule in rules
    ):
        return True
    subtree_roots = {
        str(rule.get("targetId"))
        for rule in rules
        if rule.get("scopeType") == SCOPE_DEPARTMENT_WITH_SUB
    }
    if not subtree_roots:
        return False
    parents = dict(Department.objects.filter(dept_id__in=enabled_ids).values_list("dept_id", "parent_dept_id"))
    for direct_department_id in direct_department_ids:
        current = direct_department_id
        visited: set[int] = set()
        while current is not None and current not in visited:
            if str(current) in subtree_roots:
                return True
            visited.add(current)
            current = parents.get(current)
    return False


def can_manage_organization(request, *, lock: bool = False) -> bool:
    if request_has_full_access_user_id(request):
        return True
    user_id = get_request_permission_user_id(request)
    employee = getattr(request, "auth_employee", None)
    if not user_id or employee is None or employee.user_id != user_id or not (
        employee.identity_source == Employee.IDENTITY_DINGTALK
        and employee.status == Employee.STATUS_ACTIVE
        and employee.account_status == Employee.ACCOUNT_ENABLED
    ):
        return False
    states = OrganizationPermissionState.objects
    if lock:
        states = states.select_for_update()
    state = states.filter(state_id=STATE_ID).first()
    return bool(state and _permission_allows_user(state.rules or [], user_id))


def _canonical_permission_rules(raw_rules, *, previous_rules: list[dict], directory: _OrganizationDirectory) -> list[dict]:
    if not isinstance(raw_rules, list) or len(raw_rules) > MAX_PERMISSION_RULES:
        raise OrganizationAccessError("权限规则必须是有效数组", code="INVALID_ORGANIZATION_PERMISSION_RULE")
    previous_by_key = {
        (rule.get("scopeType"), _text(rule.get("targetId"))): rule
        for rule in previous_rules
    }
    rules: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_rule in enumerate(raw_rules):
        if not isinstance(raw_rule, dict):
            raise OrganizationAccessError("权限规则必须是对象", code="INVALID_ORGANIZATION_PERMISSION_RULE")
        scope_type = _text(raw_rule.get("scopeType"))
        target_id = _text(raw_rule.get("targetId"))
        if scope_type not in SCOPE_TYPES or not target_id or len(target_id) > 64:
            raise OrganizationAccessError("权限规则的类型或目标无效", code="INVALID_ORGANIZATION_PERMISSION_RULE")
        if scope_type in DEPARTMENT_SCOPE_TYPES:
            if not target_id.isascii() or not target_id.isdigit():
                raise OrganizationAccessError("权限部门ID无效", code="INVALID_ORGANIZATION_PERMISSION_RULE")
            target_id = str(int(target_id))
        key = (scope_type, target_id)
        if key in seen:
            raise OrganizationAccessError("权限规则重复", code="DUPLICATE_ORGANIZATION_PERMISSION_RULE")
        seen.add(key)
        previous = previous_by_key.get(key, {})
        if scope_type in DEPARTMENT_SCOPE_TYPES:
            target = directory.departments.get(int(target_id))
        else:
            target = directory.employees.get(target_id)
        target_name = target.name if target else _text(previous.get("targetName"))
        if not target_name:
            raise OrganizationAccessError(
                f"权限目标不存在、未启用、已离职或账号已禁用：{target_id}",
                code="INVALID_ORGANIZATION_PERMISSION_RULE",
            )
        try:
            sort_order = int(raw_rule.get("sortOrder", index))
        except (TypeError, ValueError, OverflowError) as exc:
            raise OrganizationAccessError("权限规则排序无效", code="INVALID_ORGANIZATION_PERMISSION_RULE") from exc
        if sort_order < 0 or sort_order > MAX_SORT_ORDER:
            raise OrganizationAccessError("权限规则排序无效", code="INVALID_ORGANIZATION_PERMISSION_RULE")
        rules.append({
            "scopeType": scope_type,
            "targetId": target_id,
            "targetName": target_name,
            "sortOrder": sort_order,
        })
    return rules


def _permission_members(rules: list[dict], directory: _OrganizationDirectory) -> list[dict]:
    excluded = {
        rule["targetId"]
        for rule in rules
        if rule.get("scopeType") == SCOPE_EXCLUDED_EMPLOYEE
    }
    sources: dict[str, list[str]] = defaultdict(list)
    for rule in rules:
        scope_type = rule.get("scopeType")
        target_id = rule.get("targetId")
        if scope_type in DEPARTMENT_SCOPE_TYPES:
            department = directory.departments.get(int(target_id))
            if department is None:
                continue
            member_ids = directory.department_member_ids(
                department.dept_id,
                include_sub_departments=scope_type == SCOPE_DEPARTMENT_WITH_SUB,
            )
            source_name = f"{department.name}（含下级）" if scope_type == SCOPE_DEPARTMENT_WITH_SUB else department.name
        elif scope_type == SCOPE_EMPLOYEE:
            member_ids = {target_id} if target_id in directory.employees else set()
            source_name = "单独人员"
        else:
            continue
        for user_id in member_ids - excluded:
            if source_name not in sources[user_id]:
                sources[user_id].append(source_name)
    department_names: dict[str, list[str]] = defaultdict(list)
    for department_id, member_ids in directory.members_by_department.items():
        for user_id in member_ids:
            department_names[user_id].append(directory.departments[department_id].name)
    return [
        {
            "userId": user_id,
            "name": directory.employees[user_id].name,
            "avatarUrl": directory.employees[user_id].avatar_url,
            "departmentNames": sorted(set(department_names.get(user_id, ()))),
            "sourceNames": sources[user_id],
        }
        for user_id in sorted(sources)
    ]


def _permission_response(state: OrganizationPermissionState, *, org_revision: int | None = None) -> JsonResponse:
    directory = _OrganizationDirectory()
    rules = []
    for rule in state.rules or []:
        scope_type = rule.get("scopeType")
        target_id = _text(rule.get("targetId"))
        if scope_type in DEPARTMENT_SCOPE_TYPES:
            target = directory.departments.get(int(target_id)) if target_id.isdigit() else None
        else:
            target = directory.employees.get(target_id)
        rules.append({
            **rule,
            "permission": "admin",
            "permissionLabel": "后台管理权限",
            "scopeLabel": SCOPE_LABELS.get(scope_type, ""),
            "targetName": target.name if target else rule.get("targetName", target_id),
        })
    members = _permission_members(rules, directory)
    user_ids = [member["userId"] for member in members]
    return JsonResponse({
        "rules": rules,
        "managerUserIds": user_ids,
        "managers": [{"userId": member["userId"], "name": member["name"]} for member in members],
        "memberUserIds": user_ids,
        "memberCount": len(members),
        "effectiveMembers": members,
        "revision": max(1, int(state.revision or 1)),
        "orgRevision": get_organization_revision() if org_revision is None else org_revision,
        "canManage": True,
        "canConfigurePermissions": True,
    })


@csrf_exempt
@require_http_methods(["GET", "PUT"])
def organization_permissions(request):
    if not can_manage_organization(request):
        return JsonResponse(
            {"ok": False, "code": "ORGANIZATION_PERMISSIONS_FORBIDDEN", "error": "只有后台管理员可以设置后台管理权限"},
            status=403,
        )
    if request.method == "GET":
        state, _created = OrganizationPermissionState.objects.get_or_create(state_id=STATE_ID, defaults={"revision": 1})
        return _permission_response(state)
    try:
        payload = _parse_json_body(request)
        with transaction.atomic():
            org_state = lock_organization_state()
            org_revision = max(0, int(org_state.revision or 0))
            state, _created = OrganizationPermissionState.objects.select_for_update().get_or_create(
                state_id=STATE_ID,
                defaults={"revision": 1},
            )
            _expected_revision(
                payload.get("revision"),
                current=max(1, int(state.revision or 1)),
                field_name="revision",
                required_code="REVISION_REQUIRED",
                conflict_code="REVISION_CONFLICT",
            )
            _expected_revision(
                payload.get("orgRevision"),
                current=org_revision,
                field_name="orgRevision",
                required_code="ORG_REVISION_REQUIRED",
                conflict_code="ORG_REVISION_CONFLICT",
            )
            directory = _OrganizationDirectory()
            rules = _canonical_permission_rules(
                payload.get("rules"),
                previous_rules=state.rules or [],
                directory=directory,
            )
            members = _permission_members(rules, directory)
            state.rules = rules
            state.manager_user_ids = [member["userId"] for member in members]
            state.revision = max(1, int(state.revision or 1)) + 1
            state.save(update_fields=["rules", "manager_user_ids", "revision", "updated_at"])
    except OrganizationAccessError as exc:
        return _error_response(exc)
    return _permission_response(state, org_revision=org_revision)


def _platform_departments_response(state: PlatformDepartmentState, *, org_revision: int | None = None) -> JsonResponse:
    enabled_ids = sorted(get_platform_enabled_department_ids())
    return JsonResponse({
        "departmentIds": enabled_ids,
        "count": len(enabled_ids),
        "revision": max(1, int(state.revision or 1)),
        "orgRevision": get_organization_revision() if org_revision is None else org_revision,
    })


def _canonical_department_ids(raw_values) -> set[int]:
    if not isinstance(raw_values, list) or len(raw_values) > MAX_DEPARTMENTS:
        raise OrganizationAccessError("启用部门必须是有效数组", code="INVALID_ENABLED_DEPARTMENTS")
    all_departments = dict(Department.objects.values_list("dept_id", "parent_dept_id"))
    selected: set[int] = set()
    for raw_value in raw_values:
        if isinstance(raw_value, bool):
            raise OrganizationAccessError("启用部门ID无效", code="INVALID_ENABLED_DEPARTMENTS")
        try:
            department_id = int(raw_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise OrganizationAccessError("启用部门ID无效", code="INVALID_ENABLED_DEPARTMENTS") from exc
        if department_id not in all_departments:
            raise OrganizationAccessError(f"钉钉部门不存在：{department_id}", code="INVALID_ENABLED_DEPARTMENTS")
        selected.add(department_id)
    return selected


@csrf_exempt
@require_http_methods(["GET", "PUT"])
def platform_enabled_departments(request):
    if request.method == "PUT" and not can_manage_organization(request):
        return JsonResponse(
            {"ok": False, "code": "ENABLED_DEPARTMENTS_FORBIDDEN", "error": "只有组织架构管理员可以维护全系统启用部门"},
            status=403,
        )
    state, _created = PlatformDepartmentState.objects.get_or_create(
        state_id=STATE_ID,
        defaults={"configured": False, "revision": 1},
    )
    if request.method == "GET":
        return _platform_departments_response(state)
    try:
        payload = _parse_json_body(request)
        with transaction.atomic():
            org_state = lock_organization_state()
            current_org_revision = max(0, int(org_state.revision or 0))
            state = PlatformDepartmentState.objects.select_for_update().get(state_id=STATE_ID)
            _expected_revision(
                payload.get("revision"),
                current=max(1, int(state.revision or 1)),
                field_name="revision",
                required_code="REVISION_REQUIRED",
                conflict_code="REVISION_CONFLICT",
            )
            _expected_revision(
                payload.get("orgRevision"),
                current=current_org_revision,
                field_name="orgRevision",
                required_code="ORG_REVISION_REQUIRED",
                conflict_code="ORG_REVISION_CONFLICT",
            )
            enabled_ids = _canonical_department_ids(payload.get("departmentIds"))
            current_ids = get_platform_enabled_department_ids()
            if enabled_ids != current_ids or not state.configured:
                PlatformEnabledDepartment.objects.all().delete()
                actor_id = get_request_permission_user_id(request)
                PlatformEnabledDepartment.objects.bulk_create([
                    PlatformEnabledDepartment(department_id=department_id, enabled_by=actor_id)
                    for department_id in sorted(enabled_ids)
                ])
                state.configured = True
                state.revision = max(1, int(state.revision or 1)) + 1
                state.save(update_fields=["configured", "revision", "updated_at"])
                current_org_revision = advance_organization_revision(state=org_state)
    except OrganizationAccessError as exc:
        return _error_response(exc)
    return _platform_departments_response(state, org_revision=current_org_revision)
