import os
from typing import Any

import httpx


PAGE_LIMIT = 100


class OrganizationServiceError(Exception):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


class OrganizationRevisionChanged(OrganizationServiceError):
    pass


def _setting(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def organization_is_configured() -> bool:
    return bool(
        _setting("AUTH_ORG_INTERNAL_URL", "http://auth-backend:8000/api/internal/org")
        and _setting("AUTH_SERVICE_INTROSPECTION_SECRET")
    )


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Internal-Service": _setting("SERVICE_NAME", "competitive-backend"),
        "X-Internal-Auth-Secret": _setting("AUTH_SERVICE_INTROSPECTION_SECRET"),
    }


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not organization_is_configured():
        raise OrganizationServiceError("钉钉组织接口尚未配置", 503)
    base_url = _setting(
        "AUTH_ORG_INTERNAL_URL",
        "http://auth-backend:8000/api/internal/org",
    )
    timeout = float(_setting("AUTH_INTROSPECTION_TIMEOUT_SECONDS", "5"))
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/{path.lstrip('/')}",
            headers=_headers(),
            json=payload,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise OrganizationServiceError("钉钉组织服务暂时不可用", 503) from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise OrganizationServiceError("钉钉组织服务返回了无效响应", 503) from exc
    if response.status_code != 200 or not isinstance(data, dict) or data.get("ok") is not True:
        message = (
            str(
                data.get("error")
                or data.get("message")
                or data.get("detail")
                or "组织接口调用失败"
            ).strip()
            if isinstance(data, dict)
            else "组织接口调用失败"
        )
        status_code = response.status_code if response.status_code in {400, 401, 403} else 503
        raise OrganizationServiceError(message, status_code)
    return data


def _revision(data: dict[str, Any]) -> int:
    try:
        revision = int(data["orgRevision"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OrganizationServiceError("组织接口缺少 orgRevision", 503) from exc
    if revision < 0:
        raise OrganizationServiceError("组织接口返回了无效 orgRevision", 503)
    return revision


def _search_all(
    path: str,
    payload: dict[str, Any],
    expected_revision: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    offset = 0
    snapshot_revision = expected_revision
    while True:
        data = _post(path, {**payload, "limit": PAGE_LIMIT, "offset": offset})
        current_revision = _revision(data)
        if snapshot_revision is not None and current_revision != snapshot_revision:
            raise OrganizationRevisionChanged("读取期间组织架构发生变化", 409)
        snapshot_revision = current_revision
        page_items = data.get("items") if isinstance(data.get("items"), list) else []
        items.extend(item for item in page_items if isinstance(item, dict))
        offset += PAGE_LIMIT
        total = int(data.get("total") or 0)
        if not page_items or (total and offset >= total):
            return items, current_revision


def get_organization_snapshot(
    max_attempts: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    last_error = None
    for _attempt in range(max_attempts):
        try:
            departments, revision = _search_all(
                "departments/search",
                {"keyword": "", "includeDepartmentPath": True},
            )
            employees, revision = _search_all(
                "users/search",
                {
                    "keyword": "",
                    "status": "all",
                    "accountStatus": "all",
                    "includeDepartments": True,
                    "includeDepartmentPath": True,
                },
                revision,
            )
            return departments, employees, revision
        except OrganizationRevisionChanged as exc:
            last_error = exc
    raise OrganizationServiceError("组织架构持续变化，请稍后刷新", 503) from last_error


def get_user_department_scope(user_id: str) -> tuple[set[str], set[str]]:
    data = _post(
        "users/departments",
        {
            "userIds": [user_id],
            "status": "active",
            "accountStatus": "enabled",
            "includeDepartmentPath": True,
            "includeEmployeeProfiles": False,
        },
    )
    _revision(data)
    rows = data.get("items") if isinstance(data.get("items"), list) else []
    row = next((item for item in rows if str(item.get("userId") or "") == user_id), None)
    if not isinstance(row, dict) or row.get("matchesFilters") is not True:
        return set(), set()
    direct_ids = {str(value) for value in row.get("departmentIds", []) if str(value).strip()}
    ancestor_ids = set(direct_ids)
    for department in row.get("departments", []):
        if not isinstance(department, dict):
            continue
        for item in department.get("departmentPath", []):
            value = item.get("deptId") or item.get("id") if isinstance(item, dict) else item
            if str(value or "").strip():
                ancestor_ids.add(str(value))
    return direct_ids, ancestor_ids


def build_department_tree(departments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for item in departments:
        department_id = str(item.get("deptId") or item.get("id") or "").strip()
        if department_id:
            nodes[department_id] = {**item, "deptId": department_id, "children": []}
    roots: list[dict[str, Any]] = []
    for node in nodes.values():
        parent = nodes.get(str(node.get("parentDeptId") or "").strip())
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)

    def sort_tree(items: list[dict[str, Any]]) -> None:
        items.sort(key=lambda item: (str(item.get("name") or ""), str(item["deptId"])))
        for item in items:
            sort_tree(item["children"])

    sort_tree(roots)
    return roots
