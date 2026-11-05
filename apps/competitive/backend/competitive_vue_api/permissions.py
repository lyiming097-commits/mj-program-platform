from dataclasses import dataclass

from .models import (
    OrganizationDepartment,
    OrganizationDepartmentEmployee,
    PermissionCode,
    PermissionRule,
    PermissionScope,
)


@dataclass(frozen=True, slots=True)
class PermissionAccess:
    permissions: frozenset[str]

    @property
    def can_access(self) -> bool:
        return bool(self.permissions)

    @property
    def can_collect(self) -> bool:
        return bool(
            self.permissions & {PermissionCode.ADMIN, PermissionCode.COLLECTOR}
        )

    @property
    def can_review(self) -> bool:
        return bool(
            self.permissions & {PermissionCode.ADMIN, PermissionCode.REVIEWER}
        )

    @property
    def can_manage(self) -> bool:
        return PermissionCode.ADMIN in self.permissions


def resolve_permission_access(request) -> PermissionAccess:
    if request.auth_can_use_system_admin:
        return PermissionAccess(frozenset({PermissionCode.ADMIN}))

    rules = list(PermissionRule.objects.all())
    excluded = {
        rule.permission
        for rule in rules
        if rule.scope_type == PermissionScope.EXCLUDED_EMPLOYEE
        and rule.target_id == request.auth_user_id
    }
    direct_department_ids = {
        str(value)
        for value in OrganizationDepartmentEmployee.objects.filter(
            employee_id=request.auth_user_id
        ).values_list("department_id", flat=True)
    }
    ancestor_department_ids = set(direct_department_ids)
    if any(rule.scope_type == PermissionScope.DEPARTMENT_WITH_SUB for rule in rules):
        parent_by_id = {
            str(department_id): str(parent_id) if parent_id is not None else ""
            for department_id, parent_id in OrganizationDepartment.objects.values_list(
                "dept_id", "parent_dept_id"
            )
        }
        for department_id in direct_department_ids:
            current = department_id
            visited: set[str] = set()
            while current and current not in visited:
                visited.add(current)
                ancestor_department_ids.add(current)
                current = parent_by_id.get(current, "")
    matched: set[str] = set()
    for rule in rules:
        if rule.permission in excluded or rule.scope_type == PermissionScope.EXCLUDED_EMPLOYEE:
            continue
        if rule.scope_type == PermissionScope.EMPLOYEE and rule.target_id == request.auth_user_id:
            matched.add(rule.permission)
        elif (
            rule.scope_type == PermissionScope.DEPARTMENT
            and rule.target_id in direct_department_ids
        ):
            matched.add(rule.permission)
        elif (
            rule.scope_type == PermissionScope.DEPARTMENT_WITH_SUB
            and rule.target_id in ancestor_department_ids
        ):
            matched.add(rule.permission)
    return PermissionAccess(frozenset(matched))


def access_payload(request, access: PermissionAccess) -> dict:
    identity = request.auth_introspection
    return {
        "userId": request.auth_user_id,
        "name": request.auth_user_name,
        "avatarUrl": str(identity.get("avatarUrl") or ""),
        "actorUserId": request.auth_actor_user_id,
        "actorName": request.auth_actor_name,
        "actorDisplay": str(identity.get("actorDisplay") or request.auth_actor_name or ""),
        "isProxying": request.auth_is_proxy,
        "isSystemAdmin": bool(identity.get("isSystemAdmin")),
        "canUseSystemAdmin": request.auth_can_use_system_admin,
        "canManageEmployeeAccountStatus": bool(
            identity.get("canManageEmployeeAccountStatus")
        ),
        "permissions": sorted(access.permissions),
        "canAccess": access.can_access,
        "canCollect": access.can_collect,
        "canReview": access.can_review,
        "canManage": access.can_manage,
    }
