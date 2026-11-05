from __future__ import annotations

import os
from datetime import datetime

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from identity_api.auth.org_client import get_auth_organization_snapshot
from identity_api.models import Department, DepartmentEmployee, Employee

from .models import CableMallOrganizationSyncState


AUTH_ORG_SYNC_STATE_KEY = "auth-organization"


def _sync_ttl_seconds() -> int:
    raw_value = os.getenv("CABLE_MALL_AUTH_ORG_SYNC_TTL_SECONDS", "300").strip()
    try:
        return max(int(raw_value), 0)
    except ValueError:
        return 300


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


def _employee_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = parse_datetime(_text(value))
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _employee_status(value) -> str:
    normalized = _text(value)
    if normalized == Employee.STATUS_ACTIVE or normalized.lower() == "active":
        return Employee.STATUS_ACTIVE
    return Employee.STATUS_INACTIVE


def _employee_account_status(value) -> str:
    normalized = _text(value)
    if normalized == Employee.ACCOUNT_ENABLED or normalized.lower() == "enabled":
        return Employee.ACCOUNT_ENABLED
    return Employee.ACCOUNT_DISABLED


def sync_auth_organization_snapshot(
    department_rows: list[dict],
    employee_rows: list[dict],
    *,
    org_revision: int | None = None,
) -> dict:
    departments = {
        department_id: row
        for row in department_rows
        if isinstance(row, dict) and (department_id := _department_id(row)) is not None
    }
    employees = {
        user_id: row
        for row in employee_rows
        if isinstance(row, dict)
        and (user_id := _text(row.get("userId") or row.get("user_id") or row.get("id")))
    }
    relation_keys: set[tuple[int, str]] = set()

    with transaction.atomic():
        for department_id, row in departments.items():
            Department.objects.update_or_create(
                dept_id=department_id,
                defaults={
                    "name": _text(row.get("name")) or str(department_id),
                    "manager_user_id": _text(row.get("managerUserId") or row.get("manager_user_id")),
                    "parent_dept_id": _parent_department_id(row),
                },
            )

        for user_id, row in employees.items():
            Employee.objects.update_or_create(
                user_id=user_id,
                defaults={
                    "name": _text(row.get("rawName") or row.get("name")) or user_id,
                    "avatar_url": _text(row.get("avatarUrl") or row.get("avatar_url")),
                    "status": _employee_status(row.get("status")),
                    "account_status": _employee_account_status(row.get("accountStatus") or row.get("account_status")),
                    "handover_user_id": _text(row.get("handoverUserId") or row.get("handover_user_id")),
                    "create_time": _employee_datetime(row.get("createTime") or row.get("create_time")),
                },
            )
            for department in row.get("departments") if isinstance(row.get("departments"), list) else []:
                if not isinstance(department, dict):
                    continue
                department_id = _department_id(department)
                if department_id in departments:
                    relation_keys.add((int(department_id), user_id))

        DepartmentEmployee.objects.all().delete()
        DepartmentEmployee.objects.bulk_create([
            DepartmentEmployee(department_id=department_id, employee_id=user_id)
            for department_id, user_id in sorted(relation_keys)
        ])
        Employee.objects.exclude(user_id__in=employees).update(
            status=Employee.STATUS_INACTIVE,
            account_status=Employee.ACCOUNT_DISABLED,
        )
        Department.objects.exclude(dept_id__in=departments).delete()

        if org_revision is not None:
            state, _created = CableMallOrganizationSyncState.objects.select_for_update().get_or_create(
                state_key=AUTH_ORG_SYNC_STATE_KEY,
            )
            state.org_revision = max(0, int(org_revision or 0))
            state.synced_at = timezone.now()
            state.save(update_fields=["org_revision", "synced_at", "updated_at"])

    return {
        "departmentCount": len(departments),
        "employeeCount": len(employees),
        "relationCount": len(relation_keys),
    }


def refresh_auth_organization_snapshot(*, force: bool = False) -> dict:
    requested_at = timezone.now()
    with transaction.atomic():
        state, _created = CableMallOrganizationSyncState.objects.select_for_update().get_or_create(
            state_key=AUTH_ORG_SYNC_STATE_KEY,
        )
        if state.synced_at:
            elapsed = (requested_at - state.synced_at).total_seconds()
            if (not force and elapsed < _sync_ttl_seconds()) or (force and state.synced_at >= requested_at):
                return {"refreshed": False, "orgRevision": int(state.org_revision or 0)}

        department_rows, employee_rows, org_revision = get_auth_organization_snapshot()
        result = sync_auth_organization_snapshot(
            department_rows,
            employee_rows,
            org_revision=org_revision,
        )
        return {
            "refreshed": True,
            "departments": department_rows,
            "employees": employee_rows,
            "orgRevision": org_revision,
            **result,
        }
