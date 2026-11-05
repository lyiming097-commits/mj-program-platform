from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
import uuid
from typing import Any, Iterable


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
    return os.getenv("SERVICE_NAME", "cable-mall-backend").strip() or "cable-mall-backend"


def _timeout_seconds() -> float:
    raw_value = os.getenv("AUTH_INTROSPECTION_TIMEOUT_SECONDS", "3").strip()
    try:
        return max(float(raw_value), 0.5)
    except ValueError:
        return 3.0


def _decode_error_payload(raw_body: bytes) -> str:
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("error") or payload.get("message") or "").strip()


def _auth_org_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    base_url = _org_base_url()
    secret = _internal_secret()
    if not base_url or not secret:
        raise AuthOrgClientError("Auth organization API is not configured", 503)

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
        message = _decode_error_payload(exc.read()) or "Auth organization API rejected the request"
        status_code = exc.code if exc.code in {400, 401, 403, 409} else 503
        raise AuthOrgClientError(message, status_code) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthOrgClientError("Auth organization service unavailable", 503) from exc

    if not isinstance(data, dict) or not data.get("ok"):
        message = (
            str(data.get("error") or data.get("message") or "").strip()
            if isinstance(data, dict)
            else ""
        )
        raise AuthOrgClientError(message or "Auth organization API returned an invalid response", 503)
    return data


def _response_org_revision(response: dict[str, Any]) -> int:
    try:
        revision = int(response.get("orgRevision"))
    except (TypeError, ValueError) as exc:
        raise AuthOrgClientError("Auth organization API did not return orgRevision", 503) from exc
    if revision < 0:
        raise AuthOrgClientError("Auth organization API returned an invalid orgRevision", 503)
    return revision


def _require_org_revision(response: dict[str, Any], expected_revision: int | None) -> int:
    revision = _response_org_revision(response)
    if expected_revision is not None and revision != expected_revision:
        raise AuthOrgRevisionChanged("Auth organization changed while the snapshot was being read", 409)
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
        response = _auth_org_post(
            path,
            {
                **payload,
                "limit": AUTH_ORG_PAGE_LIMIT,
                "offset": offset,
            },
        )
        snapshot_revision = _require_org_revision(response, snapshot_revision)
        page_items = response.get("items") if isinstance(response.get("items"), list) else []
        items.extend(item for item in page_items if isinstance(item, dict))
        try:
            count = int(response.get("count") or len(page_items) or 0)
            total = int(response.get("total") or 0)
        except (TypeError, ValueError) as exc:
            raise AuthOrgClientError("Auth organization API returned invalid pagination data", 503) from exc
        offset += AUTH_ORG_PAGE_LIMIT
        if not page_items or count <= 0 or (total and offset >= total):
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
                    "status": "all",
                    "accountStatus": "all",
                    "includeDepartments": True,
                },
                expected_revision=revision,
            )
            return departments, employees, revision
        except AuthOrgRevisionChanged as exc:
            last_error = exc
    raise AuthOrgClientError(
        "Auth organization kept changing while cable mall was reading the snapshot",
        503,
    ) from last_error


def _int_sort_value(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_auth_department_tree(departments: Iterable[dict]) -> list[dict]:
    node_by_id: dict[str, dict] = {}
    for row in departments:
        dept_id = str(row.get("deptId") or row.get("dept_id") or row.get("id") or "").strip()
        if not dept_id:
            continue
        node = dict(row)
        node["children"] = []
        node_by_id[dept_id] = node

    roots: list[dict] = []
    for node in node_by_id.values():
        parent_id = str(node.get("parentDeptId") or node.get("parent_dept_id") or "").strip()
        parent = node_by_id.get(parent_id)
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)

    def sort_nodes(nodes: list[dict]) -> list[dict]:
        nodes.sort(key=lambda item: (
            _int_sort_value(item.get("deptId") or item.get("id")),
            str(item.get("name") or ""),
        ))
        for child in nodes:
            sort_nodes(child.get("children") or [])
        return nodes

    return sort_nodes(roots)
