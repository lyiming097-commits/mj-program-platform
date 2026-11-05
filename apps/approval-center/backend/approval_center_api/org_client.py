from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
import uuid
from typing import Any


AUTH_ORG_PAGE_LIMIT = 100


class AuthOrgClientError(Exception):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


class AuthOrgRevisionChanged(AuthOrgClientError):
    pass


def _org_base_url() -> str:
    return os.getenv(
        "AUTH_ORG_INTERNAL_URL",
        "http://auth-backend:8000/api/internal/org",
    ).strip().rstrip("/")


def _internal_secret() -> str:
    return os.getenv("AUTH_SERVICE_INTROSPECTION_SECRET", "").strip()


def _service_name() -> str:
    return os.getenv("SERVICE_NAME", "approval-center-backend").strip() or "approval-center-backend"


def _timeout_seconds() -> float:
    try:
        return max(float(os.getenv("AUTH_INTROSPECTION_TIMEOUT_SECONDS", "3").strip()), 0.5)
    except ValueError:
        return 3.0


def _decode_error(raw_body: bytes) -> str:
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("error") or payload.get("message") or "").strip()


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    base_url = _org_base_url()
    secret = _internal_secret()
    if not base_url or not secret:
        raise AuthOrgClientError("Auth 组织架构接口未配置", 503)

    request = urllib.request.Request(
        f"{base_url}/{path.lstrip('/')}",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Internal-Auth-Secret": secret,
            "X-Internal-Service": _service_name(),
            "X-Request-Id": uuid.uuid4().hex,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        message = _decode_error(exc.read()) or "Auth 组织架构接口拒绝了请求"
        status_code = exc.code if exc.code in {400, 401, 403, 409} else 503
        raise AuthOrgClientError(message, status_code) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthOrgClientError("Auth 组织架构服务暂不可用", 503) from exc

    if not isinstance(data, dict) or data.get("ok") is not True:
        message = (
            str(data.get("error") or data.get("message") or "").strip()
            if isinstance(data, dict)
            else ""
        )
        raise AuthOrgClientError(message or "Auth 组织架构接口返回格式错误", 503)
    return data


def _response_revision(data: dict[str, Any], expected: int | None = None) -> int:
    try:
        revision = int(data.get("orgRevision"))
    except (TypeError, ValueError) as exc:
        raise AuthOrgClientError("Auth 组织架构接口未返回有效版本", 503) from exc
    if revision < 0:
        raise AuthOrgClientError("Auth 组织架构接口返回了无效版本", 503)
    if expected is not None and revision != expected:
        raise AuthOrgRevisionChanged("读取期间组织架构发生变化", 409)
    return revision


def _search_all(
    path: str,
    payload: dict[str, Any],
    *,
    expected_revision: int | None = None,
) -> tuple[list[dict], int]:
    items: list[dict] = []
    offset = 0
    snapshot_revision = expected_revision
    while True:
        data = _post(
            path,
            {
                **payload,
                "limit": AUTH_ORG_PAGE_LIMIT,
                "offset": offset,
            },
        )
        snapshot_revision = _response_revision(data, snapshot_revision)
        page = data.get("items") if isinstance(data.get("items"), list) else []
        items.extend(item for item in page if isinstance(item, dict))
        offset += AUTH_ORG_PAGE_LIMIT
        total = int(data.get("total") or 0)
        if not page or (total and offset >= total) or (not total and len(page) < AUTH_ORG_PAGE_LIMIT):
            break
    return items, int(snapshot_revision or 0)


def get_auth_organization_snapshot(*, max_attempts: int = 3) -> tuple[list[dict], list[dict], int]:
    last_error: AuthOrgRevisionChanged | None = None
    for _attempt in range(max(int(max_attempts or 1), 1)):
        try:
            departments, revision = _search_all(
                "departments/search",
                {"keyword": "", "includeDepartmentPath": False},
            )
            employees, revision = _search_all(
                "users/search",
                {
                    "keyword": "",
                    "status": "active",
                    "accountStatus": "enabled",
                    "includeDepartments": True,
                },
                expected_revision=revision,
            )
            return departments, employees, revision
        except AuthOrgRevisionChanged as exc:
            last_error = exc
    raise AuthOrgClientError("读取组织架构时数据持续变化，请稍后重试", 503) from last_error


def get_auth_user_department_scope(user_id: str) -> dict[str, Any]:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return {
            "directDepartmentIds": set(),
            "ancestorDepartmentIds": set(),
            "orgRevision": 0,
        }

    data = _post(
        "users/departments",
        {
            "userIds": [normalized_user_id],
            "status": "active",
            "accountStatus": "enabled",
            "includeDepartmentPath": True,
            "includeEmployeeProfiles": False,
        },
    )
    revision = _response_revision(data)
    rows = data.get("items") if isinstance(data.get("items"), list) else []
    row = next(
        (
            item
            for item in rows
            if isinstance(item, dict)
            and str(item.get("userId") or "").strip() == normalized_user_id
        ),
        None,
    )
    if not row or row.get("matchesFilters") is not True:
        return {
            "directDepartmentIds": set(),
            "ancestorDepartmentIds": set(),
            "orgRevision": revision,
        }

    direct_department_ids = {
        str(value).strip()
        for value in row.get("departmentIds") or []
        if str(value).strip()
    }
    ancestor_department_ids = set(direct_department_ids)
    for department in row.get("departments") if isinstance(row.get("departments"), list) else []:
        if not isinstance(department, dict):
            continue
        department_id = str(department.get("deptId") or department.get("id") or "").strip()
        if department_id:
            ancestor_department_ids.add(department_id)
        path = department.get("departmentPath") if isinstance(department.get("departmentPath"), list) else []
        for ancestor in path:
            if not isinstance(ancestor, dict):
                continue
            ancestor_id = str(ancestor.get("deptId") or ancestor.get("id") or "").strip()
            if ancestor_id:
                ancestor_department_ids.add(ancestor_id)

    return {
        "directDepartmentIds": direct_department_ids,
        "ancestorDepartmentIds": ancestor_department_ids,
        "orgRevision": revision,
    }


def build_auth_department_tree(departments: list[dict]) -> list[dict]:
    nodes: dict[str, dict] = {}
    for row in departments:
        if not isinstance(row, dict):
            continue
        department_id = str(row.get("deptId") or row.get("id") or "").strip()
        if not department_id:
            continue
        nodes[department_id] = {**row, "children": []}

    roots: list[dict] = []
    for department_id, node in nodes.items():
        parent_id = str(node.get("parentDeptId") or "").strip()
        parent = nodes.get(parent_id)
        if parent is None or parent_id == department_id:
            roots.append(node)
        else:
            parent["children"].append(node)

    def sort_rows(rows: list[dict]) -> list[dict]:
        rows.sort(
            key=lambda item: (
                int(item.get("order") or item.get("sortOrder") or 0),
                str(item.get("name") or ""),
                str(item.get("deptId") or item.get("id") or ""),
            )
        )
        for row in rows:
            sort_rows(row.get("children") or [])
        return rows

    return sort_rows(roots)
