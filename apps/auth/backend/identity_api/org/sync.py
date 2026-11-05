import os
import time
from collections import deque
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from ..dingtalk.client import (
    DingTalkAPIError,
    _get_app_access_token,
    _get_user_detail_by_userid,
    _pick_first,
    _request_json,
)
from ..models import Department, DepartmentEmployee, DepartmentManager, Employee
from .revision import advance_organization_revision, lock_organization_state


DING_DEPARTMENT_DETAIL_URL = "https://oapi.dingtalk.com/topapi/v2/department/get"
DING_DEPARTMENT_LIST_SUB_URL = "https://oapi.dingtalk.com/topapi/v2/department/listsub"
DING_DEPARTMENT_USER_LIST_URL = "https://oapi.dingtalk.com/topapi/v2/user/list"


def _request_topapi_result(app_access_token: str, url: str, payload: dict[str, Any]) -> Any:
    max_attempts = max(1, int(os.getenv("DINGTALK_ORG_SYNC_RETRIES", "3") or "3"))
    retry_sleep = max(0.0, float(os.getenv("DINGTALK_ORG_SYNC_RETRY_SLEEP", "2") or "2"))
    last_detail: dict[str, Any] | None = None

    for attempt in range(1, max_attempts + 1):
        response, response_payload = _request_json(
            "POST",
            f"{url}?access_token={app_access_token}",
            json=payload,
        )
        errcode = response_payload.get("errcode") if isinstance(response_payload, dict) else None
        if response.status_code < 400 and errcode in (0, "0"):
            if isinstance(response_payload, dict) and "result" in response_payload:
                return response_payload["result"]
            return response_payload

        last_detail = {
            "url": url,
            "payload": payload,
            "attempt": attempt,
            "maxAttempts": max_attempts,
            "statusCode": response.status_code,
            "response": response_payload,
        }
        if attempt < max_attempts:
            time.sleep(retry_sleep * attempt)

    raise DingTalkAPIError(
        "DingTalk organization sync request failed",
        detail=last_detail,
    )


def _split_userids(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _extract_manager_userids(payload: dict[str, Any]) -> list[str]:
    candidates = [
        payload.get("deptManagerUseridList"),
        payload.get("dept_manager_userid_list"),
        payload.get("managerUserId"),
        payload.get("managerUserid"),
        payload.get("leaderUserId"),
        payload.get("leaderUserid"),
    ]
    for candidate in candidates:
        userids = _split_userids(candidate)
        if userids:
            return list(dict.fromkeys(userids))
    return []


def _get_department_detail(app_access_token: str, dept_id: int) -> dict[str, Any]:
    result = _request_topapi_result(
        app_access_token,
        DING_DEPARTMENT_DETAIL_URL,
        {
            "dept_id": dept_id,
            "language": "zh_CN",
        },
    )
    if not isinstance(result, dict):
        raise DingTalkAPIError(
            "DingTalk department detail response is invalid",
            detail=result,
        )
    return result


def _list_sub_departments(app_access_token: str, dept_id: int) -> list[dict[str, Any]]:
    result = _request_topapi_result(
        app_access_token,
        DING_DEPARTMENT_LIST_SUB_URL,
        {"dept_id": dept_id},
    )
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        for key in ("list", "departments", "dept_list"):
            value = result.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise DingTalkAPIError(
        "DingTalk sub-department response is invalid",
        detail={"departmentId": dept_id, "result": result},
    )


def _response_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _list_department_users(app_access_token: str, dept_id: int) -> list[dict[str, Any]]:
    cursor = 0
    users: list[dict[str, Any]] = []
    seen_cursors: set[int] = set()
    max_pages = max(1, int(os.getenv("DINGTALK_ORG_SYNC_MAX_PAGES_PER_DEPARTMENT", "1000") or "1000"))

    for _page_number in range(max_pages):
        if cursor in seen_cursors:
            raise DingTalkAPIError(
                "DingTalk employee pagination returned a repeated cursor",
                detail={"departmentId": dept_id, "cursor": cursor},
            )
        seen_cursors.add(cursor)
        result = _request_topapi_result(
            app_access_token,
            DING_DEPARTMENT_USER_LIST_URL,
            {
                "dept_id": dept_id,
                "cursor": cursor,
                "size": 100,
                "language": "zh_CN",
            },
        )
        if isinstance(result, dict):
            batch = _pick_first(result.get("list"), result.get("result"))
            if not isinstance(batch, list):
                raise DingTalkAPIError(
                    "DingTalk department employee response is missing a list",
                    detail={"departmentId": dept_id, "cursor": cursor, "result": result},
                )
            has_more = _response_bool(_pick_first(result.get("has_more"), result.get("hasMore")))
            next_cursor = _pick_first(
                result.get("next_cursor"),
                result.get("nextCursor"),
            )
        elif isinstance(result, list):
            batch = result
            has_more = False
            next_cursor = None
        else:
            batch = []
            has_more = False
            next_cursor = None

        users.extend(item for item in batch if isinstance(item, dict))

        if not has_more:
            return users
        if next_cursor in (None, ""):
            raise DingTalkAPIError(
                "DingTalk employee pagination did not return next_cursor",
                detail={"departmentId": dept_id, "cursor": cursor},
            )
        try:
            next_cursor_value = int(next_cursor)
        except (TypeError, ValueError) as exc:
            raise DingTalkAPIError(
                "DingTalk employee pagination returned an invalid next_cursor",
                detail={"departmentId": dept_id, "cursor": cursor, "nextCursor": next_cursor},
            ) from exc
        if next_cursor_value == cursor:
            raise DingTalkAPIError(
                "DingTalk employee pagination did not advance",
                detail={"departmentId": dept_id, "cursor": cursor},
            )
        cursor = next_cursor_value

    raise DingTalkAPIError(
        "DingTalk employee pagination exceeded the page safety limit",
        detail={"departmentId": dept_id, "maxPages": max_pages},
    )


def _normalize_department(raw_department: dict[str, Any], fallback_dept_id: int) -> dict[str, Any]:
    dept_id = int(_pick_first(raw_department.get("dept_id"), raw_department.get("deptId"), fallback_dept_id))
    parent_dept_id = _pick_first(
        raw_department.get("parent_id"),
        raw_department.get("parentId"),
        raw_department.get("parentDeptId"),
    )
    manager_user_ids = _extract_manager_userids(raw_department)
    return {
        "dept_id": dept_id,
        "name": str(_pick_first(raw_department.get("name"), raw_department.get("dept_name"), dept_id)),
        "manager_user_id": manager_user_ids[0] if manager_user_ids else "",
        "manager_user_ids": manager_user_ids,
        "parent_dept_id": int(parent_dept_id) if parent_dept_id not in (None, "") else None,
    }


def _normalize_employee(
    raw_user: dict[str, Any],
    *,
    fallback_user_id: str,
    fallback_name: str,
) -> dict[str, Any]:
    user_id = str(_pick_first(raw_user.get("userid"), raw_user.get("userId"), fallback_user_id))
    active_value = raw_user.get("active")
    status = Employee.STATUS_INACTIVE if active_value is False else Employee.STATUS_ACTIVE
    account_status = Employee.ACCOUNT_DISABLED if status == Employee.STATUS_INACTIVE else Employee.ACCOUNT_ENABLED
    create_time = _parse_dingtalk_create_time(
        _pick_first(
            raw_user.get("create_time"),
            raw_user.get("createTime"),
        )
    )
    return {
        "user_id": user_id,
        "name": str(_pick_first(raw_user.get("name"), raw_user.get("nick"), fallback_name, user_id)),
        "avatar_url": str(
            _pick_first(
                raw_user.get("avatarUrl"),
                raw_user.get("avatar"),
                raw_user.get("avatar_url"),
                "",
            )
            or ""
        ),
        "status": status,
        "account_status": account_status,
        "handover_user_id": "",
        "create_time": create_time,
    }


def _parse_dingtalk_create_time(value: Any):
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(
                (value / 1000) if value > 10_000_000_000 else value,
                tz=timezone.get_current_timezone(),
            )
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed.astimezone(timezone.get_current_timezone())


def _maximum_drop_ratio(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return min(max(value, 0.0), 1.0)


def _validate_snapshot_size(
    *,
    previous_department_count: int,
    previous_employee_count: int,
    previous_membership_count: int,
    department_count: int,
    employee_count: int,
    membership_count: int,
) -> None:
    if department_count <= 0 or employee_count <= 0 or membership_count <= 0:
        raise DingTalkAPIError(
            "Organization snapshot was rejected because it is empty",
            detail={
                "requiresManualReview": True,
                "departmentCount": department_count,
                "employeeCount": employee_count,
                "membershipCount": membership_count,
            },
        )
    counts = {
        "departments": (previous_department_count, department_count, _maximum_drop_ratio("DINGTALK_ORG_SYNC_MAX_DEPARTMENT_DROP_RATIO", 0.35)),
        "employees": (previous_employee_count, employee_count, _maximum_drop_ratio("DINGTALK_ORG_SYNC_MAX_EMPLOYEE_DROP_RATIO", 0.25)),
        "memberships": (previous_membership_count, membership_count, _maximum_drop_ratio("DINGTALK_ORG_SYNC_MAX_MEMBERSHIP_DROP_RATIO", 0.35)),
    }
    violations = []
    for label, (previous_count, current_count, maximum_drop_ratio) in counts.items():
        if previous_count <= 0:
            continue
        drop_ratio = max(previous_count - current_count, 0) / previous_count
        if current_count == 0 or drop_ratio > maximum_drop_ratio:
            violations.append(
                {
                    "type": label,
                    "previousCount": previous_count,
                    "fetchedCount": current_count,
                    "dropRatio": round(drop_ratio, 4),
                    "maximumDropRatio": maximum_drop_ratio,
                }
            )
    if violations:
        raise DingTalkAPIError(
            "Organization snapshot was rejected because the fetched data decreased abnormally",
            detail={"requiresManualReview": True, "violations": violations},
        )


def _validate_user_detail_errors(*, error_count: int, employee_count: int) -> None:
    if error_count <= 0 or employee_count <= 0:
        return
    maximum_error_ratio = _maximum_drop_ratio("DINGTALK_ORG_SYNC_MAX_USER_DETAIL_ERROR_RATIO", 0.05)
    error_ratio = error_count / employee_count
    if error_ratio > maximum_error_ratio:
        raise DingTalkAPIError(
            "Organization snapshot was rejected because too many employee details failed",
            detail={
                "requiresManualReview": True,
                "userDetailErrorCount": error_count,
                "employeeCount": employee_count,
                "userDetailErrorRatio": round(error_ratio, 4),
                "maximumUserDetailErrorRatio": maximum_error_ratio,
            },
        )


def _sync_department_relations(model, expected, fields, now) -> bool:
    """Preserve unchanged relationship IDs/timestamps and write only real deltas.

    Called while holding the organization state lock. Keys are stable department
    and employee IDs; ordering metadata matters for department managers.
    """
    existing = {
        (row[1], row[2]): (row[0], tuple(row[3:]))
        for row in model.objects.values_list('id', 'department_id', 'employee_id', *fields)
    }
    removed = [row_id for key, (row_id, _) in existing.items() if key not in expected]
    created, updated = [], []
    for (department_id, employee_id), values in expected.items():
        old = existing.get((department_id, employee_id))
        if old is not None and old[1] == values:
            continue
        row = model(department_id=department_id, employee_id=employee_id,
                    **dict(zip(fields, values)), updated_at=now)
        if old is None:
            created.append(row)
        else:
            row.pk = old[0]
            updated.append(row)
    if removed:
        model.objects.filter(pk__in=removed).delete()
    if created:
        model.objects.bulk_create(created)
    if updated:
        model.objects.bulk_update(updated, [*fields, 'updated_at'])
    return bool(removed or created or updated)


def sync_organization_contacts() -> dict[str, Any]:
    app_access_token = _get_app_access_token()
    root_dept_id = int(os.getenv("DINGTALK_ROOT_DEPT_ID", "1"))
    previous_department_ids = set(Department.objects.values_list("dept_id", flat=True))
    existing_employee_ids = set(
        Employee.objects.filter(identity_source=Employee.IDENTITY_DINGTALK).values_list("user_id", flat=True)
    )
    previous_employee_ids = set(
        Employee.objects.filter(
            identity_source=Employee.IDENTITY_DINGTALK,
            status=Employee.STATUS_ACTIVE,
        ).values_list("user_id", flat=True)
    )
    previous_membership_count = DepartmentEmployee.objects.count()

    departments_by_id: dict[int, dict[str, Any]] = {}
    membership_pairs: set[tuple[int, str]] = set()
    users_by_id: dict[str, dict[str, Any]] = {}
    user_detail_error_count = 0
    user_detail_error_user_ids: set[str] = set()
    queue: deque[int] = deque([root_dept_id])
    visited: set[int] = set()

    while queue:
        dept_id = queue.popleft()
        if dept_id in visited:
            continue

        raw_detail = _get_department_detail(app_access_token, dept_id)
        department = _normalize_department(raw_detail, dept_id)
        departments_by_id[department["dept_id"]] = department
        visited.add(department["dept_id"])

        for child in _list_sub_departments(app_access_token, department["dept_id"]):
            child_id = _pick_first(child.get("dept_id"), child.get("deptId"))
            if child_id in (None, ""):
                continue
            child_int = int(child_id)
            if child_int not in visited:
                queue.append(child_int)

    if not departments_by_id:
        raise DingTalkAPIError("No departments were fetched from DingTalk")

    for dept_id in departments_by_id:
        for raw_user in _list_department_users(app_access_token, dept_id):
            user_id = _pick_first(raw_user.get("userid"), raw_user.get("userId"))
            if not user_id:
                continue
            user_id = str(user_id)
            membership_pairs.add((dept_id, user_id))
            if user_id in users_by_id:
                continue
            raw_detail_user = raw_user
            try:
                detail = _get_user_detail_by_userid(app_access_token, user_id)
                if isinstance(detail, dict):
                    raw_detail_user = {**raw_user, **detail}
            except DingTalkAPIError:
                user_detail_error_count += 1
                user_detail_error_user_ids.add(user_id)
            normalized_employee = _normalize_employee(
                raw_detail_user,
                fallback_user_id=user_id,
                fallback_name=str(_pick_first(raw_user.get("name"), raw_user.get("nick"), user_id)),
            )
            normalized_employee["detail_complete"] = user_id not in user_detail_error_user_ids
            users_by_id[user_id] = normalized_employee

    _validate_user_detail_errors(
        error_count=user_detail_error_count,
        employee_count=len(users_by_id),
    )
    new_employee_detail_error_ids = sorted(user_detail_error_user_ids - existing_employee_ids)
    if new_employee_detail_error_ids:
        raise DingTalkAPIError(
            "Organization snapshot was rejected because new employee details could not be loaded",
            detail={
                "requiresManualReview": False,
                "newEmployeeDetailErrorCount": len(new_employee_detail_error_ids),
                "newEmployeeDetailErrorUserIds": new_employee_detail_error_ids[:100],
            },
        )

    _validate_snapshot_size(
        previous_department_count=len(previous_department_ids),
        previous_employee_count=len(previous_employee_ids),
        previous_membership_count=previous_membership_count,
        department_count=len(departments_by_id),
        employee_count=len(users_by_id),
        membership_count=len(membership_pairs),
    )

    now = timezone.now()
    department_objects = [
        Department(
            dept_id=item["dept_id"],
            name=item["name"],
            manager_user_id=item["manager_user_id"],
            manager_user_ids=item["manager_user_ids"],
            parent_dept_id=item["parent_dept_id"],
            updated_at=now,
        )
        for item in departments_by_id.values()
    ]
    employee_objects = [
        Employee(
            user_id=item["user_id"],
            identity_source=Employee.IDENTITY_DINGTALK,
            name=item["name"],
            avatar_url=item["avatar_url"],
            status=item["status"],
            account_status=item["account_status"],
            handover_user_id=item["handover_user_id"],
            create_time=item["create_time"],
            updated_at=now,
        )
        for item in users_by_id.values()
    ]

    with transaction.atomic():
        organization_state = lock_organization_state()
        organization_changed = False
        resigning_user_ids = {
            employee.user_id
            for employee in Employee.objects.filter(
                identity_source=Employee.IDENTITY_DINGTALK,
                status=Employee.STATUS_ACTIVE,
            )
            if employee.user_id not in users_by_id
            or (
                users_by_id[employee.user_id].get("detail_complete", True)
                and users_by_id[employee.user_id]["status"] == Employee.STATUS_INACTIVE
            )
        }
        former_dingtalk_by_user: dict[str, list[dict]] = {user_id: [] for user_id in resigning_user_ids}
        if resigning_user_ids:
            departments_before_sync = Department.objects.in_bulk(field_name="dept_id")

            def former_dingtalk_path(dept_id: int) -> str:
                names: list[str] = []
                visited: set[int] = set()
                while dept_id in departments_before_sync and dept_id not in visited:
                    visited.add(dept_id)
                    department = departments_before_sync[dept_id]
                    names.append(department.name)
                    dept_id = department.parent_dept_id
                return " / ".join(reversed(names))

            for relation in (
                DepartmentEmployee.objects.filter(employee_id__in=resigning_user_ids)
                .select_related("department")
                .order_by("department_id")
            ):
                former_dingtalk_by_user[relation.employee_id].append({
                    "deptId": relation.department_id,
                    "name": relation.department.name,
                    "pathText": former_dingtalk_path(relation.department_id),
                })

        removed_departments = Department.objects.exclude(dept_id__in=departments_by_id.keys())
        if removed_departments.exists():
            removed_departments.delete()
            organization_changed = True
        existing_departments = Department.objects.in_bulk(field_name="dept_id")
        departments_to_create: list[Department] = []
        departments_to_update: list[Department] = []
        for department in department_objects:
            existing_department = existing_departments.get(department.dept_id)
            if existing_department is None:
                departments_to_create.append(department)
                continue
            fields = ('name', 'manager_user_id', 'manager_user_ids', 'parent_dept_id')
            if all(getattr(existing_department, field) == getattr(department, field) for field in fields):
                continue
            for field in fields:
                setattr(existing_department, field, getattr(department, field))
            existing_department.updated_at = now
            departments_to_update.append(existing_department)

        if departments_to_create:
            Department.objects.bulk_create(departments_to_create)
            organization_changed = True
        if departments_to_update:
            Department.objects.bulk_update(
                departments_to_update,
                ["name", "manager_user_id", "manager_user_ids", "parent_dept_id", "updated_at"],
            )
            organization_changed = True

        if employee_objects:
            existing_employees = Employee.objects.filter(
                identity_source=Employee.IDENTITY_DINGTALK,
            ).in_bulk(field_name="user_id")
            employees_to_create: list[Employee] = []
            employees_to_update: list[Employee] = []
            for employee in employee_objects:
                existing_employee = existing_employees.get(employee.user_id)
                if existing_employee is None:
                    employees_to_create.append(employee)
                    continue
                source_employee = users_by_id.get(employee.user_id, {})
                if not source_employee.get("detail_complete", True):
                    continue
                profile_fields = (
                    'name', 'avatar_url', 'status', 'account_status', 'handover_user_id',
                    'former_dingtalk_departments', 'former_organization_recorded_at', 'auth_version', 'create_time',
                )
                before = tuple(getattr(existing_employee, field) for field in profile_fields)
                previous_status = existing_employee.status
                previous_account_status = existing_employee.account_status
                existing_employee.name = employee.name
                existing_employee.avatar_url = employee.avatar_url
                existing_employee.status = employee.status
                if employee.create_time is not None:
                    existing_employee.create_time = employee.create_time
                if employee.status == Employee.STATUS_ACTIVE:
                    if not existing_employee.account_status:
                        existing_employee.account_status = Employee.ACCOUNT_ENABLED
                    existing_employee.handover_user_id = ""
                    existing_employee.former_dingtalk_departments = []
                    existing_employee.former_organization_recorded_at = None
                else:
                    existing_employee.account_status = Employee.ACCOUNT_DISABLED
                    if employee.user_id in resigning_user_ids:
                        existing_employee.former_dingtalk_departments = former_dingtalk_by_user[employee.user_id]
                        existing_employee.former_organization_recorded_at = now
                if (
                    previous_status != existing_employee.status
                    or previous_account_status != existing_employee.account_status
                ):
                    existing_employee.auth_version += 1
                if before != tuple(getattr(existing_employee, field) for field in profile_fields):
                    existing_employee.updated_at = now
                    employees_to_update.append(existing_employee)

            if employees_to_create:
                Employee.objects.bulk_create(employees_to_create)
                organization_changed = True
            if employees_to_update:
                Employee.objects.bulk_update(
                    employees_to_update,
                    ["name", "avatar_url", "status", "account_status", "handover_user_id", "former_dingtalk_departments", "former_organization_recorded_at", "auth_version", "create_time", "updated_at"],
                )
                organization_changed = True

        missing_employees = list(
            Employee.objects.filter(identity_source=Employee.IDENTITY_DINGTALK).exclude(
                user_id__in=users_by_id.keys(),
            )
        )
        employees_to_disable: list[Employee] = []
        for missing_employee in missing_employees:
            if (
                missing_employee.status == Employee.STATUS_INACTIVE
                and missing_employee.account_status == Employee.ACCOUNT_DISABLED
            ):
                continue
            missing_employee.status = Employee.STATUS_INACTIVE
            missing_employee.account_status = Employee.ACCOUNT_DISABLED
            if missing_employee.user_id in resigning_user_ids:
                missing_employee.former_dingtalk_departments = former_dingtalk_by_user[missing_employee.user_id]
                missing_employee.former_organization_recorded_at = now
            missing_employee.auth_version += 1
            missing_employee.updated_at = now
            employees_to_disable.append(missing_employee)

        if employees_to_disable:
            Employee.objects.bulk_update(
                employees_to_disable,
                ["status", "account_status", "former_dingtalk_departments", "former_organization_recorded_at", "auth_version", "updated_at"],
            )
            organization_changed = True

        memberships_changed = _sync_department_relations(
            DepartmentEmployee, {pair: () for pair in sorted(membership_pairs)}, (), now,
        )
        manager_user_ids = {
            user_id
            for department in departments_by_id.values()
            for user_id in department.get("manager_user_ids", [])
        }
        existing_manager_user_ids = set(
            Employee.objects.filter(
                identity_source=Employee.IDENTITY_DINGTALK,
                user_id__in=manager_user_ids,
            ).values_list("user_id", flat=True)
        )
        managers_changed = _sync_department_relations(
            DepartmentManager,
            {
                (department['dept_id'], user_id): (index == 0, index)
                for department in departments_by_id.values()
                for index, user_id in enumerate(department.get("manager_user_ids", []))
                if user_id in existing_manager_user_ids
            },
            ('is_primary', 'sort_order'), now,
        )
        organization_changed = organization_changed or memberships_changed or managers_changed
        if organization_changed:
            organization_revision = advance_organization_revision(state=organization_state, synced_at=now)
        else:
            # A successful refresh is not a directory change. Keep clients'
            # snapshots valid while still reporting that synchronization ran.
            organization_state.synced_at = now
            organization_state.save(update_fields=['synced_at', 'updated_at'])
            organization_revision = max(int(organization_state.revision or 0), 0)
    current_department_ids = set(departments_by_id)
    current_employee_ids = set(users_by_id)
    return {
        "rootDeptId": root_dept_id,
        "departmentCount": len(departments_by_id),
        "employeeCount": len(users_by_id),
        "membershipCount": len(membership_pairs),
        "managerRelationCount": DepartmentManager.objects.count(),
        "missingManagerCount": len(manager_user_ids - existing_manager_user_ids),
        "userDetailErrorCount": user_detail_error_count,
        "userDetailFallbackCount": user_detail_error_count,
        "orgRevision": organization_revision,
        "organizationChanged": organization_changed,
        "departmentAddedCount": len(current_department_ids - previous_department_ids),
        "departmentRemovedCount": len(previous_department_ids - current_department_ids),
        "employeeAddedCount": len(current_employee_ids - previous_employee_ids),
        "employeeMissingCount": len(previous_employee_ids - current_employee_ids),
    }
