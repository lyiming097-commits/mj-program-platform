from django.db import transaction
from django.utils import timezone

from .models import (
    OrganizationDepartment,
    OrganizationDepartmentEmployee,
    OrganizationEmployee,
    OrganizationSyncState,
)
from .org_client import get_organization_snapshot


AUTH_ORG_SYNC_TTL_SECONDS = 300
AUTH_ORG_SYNC_STATE_KEY = "auth-organization"


def _text(value) -> str:
    return str(value or "").strip()


def _department_id(row: dict) -> int | None:
    try:
        return int(row.get("deptId") or row.get("dept_id") or row.get("id"))
    except (TypeError, ValueError):
        return None


def _parent_department_id(row: dict) -> int | None:
    value = row.get("parentDeptId", row.get("parent_dept_id"))
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sync_organization_snapshot(
    departments: list[dict],
    employees: list[dict],
) -> dict:
    department_rows = {
        department_id: row
        for row in departments
        if isinstance(row, dict)
        and (department_id := _department_id(row)) is not None
    }
    employee_rows = {
        user_id: row
        for row in employees
        if isinstance(row, dict)
        and (user_id := _text(row.get("userId") or row.get("user_id") or row.get("id")))
    }
    relation_keys: set[tuple[int, str]] = set()

    with transaction.atomic():
        for department_id, row in department_rows.items():
            OrganizationDepartment.objects.update_or_create(
                dept_id=department_id,
                defaults={
                    "name": _text(row.get("name")) or str(department_id),
                    "manager_user_id": _text(
                        row.get("managerUserId") or row.get("manager_user_id")
                    ),
                    "parent_dept_id": _parent_department_id(row),
                },
            )

        for user_id, row in employee_rows.items():
            OrganizationEmployee.objects.update_or_create(
                user_id=user_id,
                defaults={
                    "name": _text(row.get("rawName") or row.get("name")) or user_id,
                    "avatar_url": _text(row.get("avatarUrl") or row.get("avatar_url")),
                    "status": _text(row.get("status")) or "在职",
                    "account_status": _text(
                        row.get("accountStatus") or row.get("account_status")
                    ) or "启用",
                },
            )
            memberships = row.get("departments")
            for department in memberships if isinstance(memberships, list) else []:
                if not isinstance(department, dict):
                    continue
                department_id = _department_id(department)
                if department_id in department_rows:
                    relation_keys.add((int(department_id), user_id))

        if employee_rows:
            OrganizationDepartmentEmployee.objects.all().delete()
            OrganizationDepartmentEmployee.objects.bulk_create(
                [
                    OrganizationDepartmentEmployee(
                        department_id=department_id,
                        employee_id=user_id,
                    )
                    for department_id, user_id in sorted(relation_keys)
                ]
            )
            OrganizationEmployee.objects.exclude(user_id__in=employee_rows).update(
                status="离职",
                account_status="禁用",
            )

    return {
        "departmentCount": len(department_rows),
        "employeeCount": len(employee_rows),
        "relationCount": len(relation_keys),
    }


def refresh_organization_snapshot(*, force: bool = False) -> dict:
    requested_at = timezone.now()
    state = OrganizationSyncState.objects.filter(
        state_key=AUTH_ORG_SYNC_STATE_KEY,
    ).first()
    if state and state.synced_at:
        elapsed = (requested_at - state.synced_at).total_seconds()
        if (not force and elapsed < AUTH_ORG_SYNC_TTL_SECONDS) or (
            force and state.synced_at >= requested_at
        ):
            return {
                "refreshed": False,
                "orgRevision": int(state.org_revision or 0),
            }

    # Do not hold a database lock while waiting on the auth service. Concurrent
    # callers may fetch the same snapshot, but only one will materialize it below.
    departments, employees, org_revision = get_organization_snapshot()
    with transaction.atomic():
        state, _created = OrganizationSyncState.objects.select_for_update().get_or_create(
            state_key=AUTH_ORG_SYNC_STATE_KEY,
        )
        if state.synced_at:
            elapsed = (requested_at - state.synced_at).total_seconds()
            if (not force and elapsed < AUTH_ORG_SYNC_TTL_SECONDS) or (
                force and state.synced_at >= requested_at
            ):
                return {
                    "refreshed": False,
                    "orgRevision": int(state.org_revision or 0),
                }
        result = sync_organization_snapshot(departments, employees)
        state.org_revision = max(0, int(org_revision or 0))
        state.synced_at = timezone.now()
        state.save(update_fields=["org_revision", "synced_at", "updated_at"])
        return {
            "refreshed": True,
            "departments": departments,
            "employees": employees,
            "orgRevision": org_revision,
            **result,
        }
