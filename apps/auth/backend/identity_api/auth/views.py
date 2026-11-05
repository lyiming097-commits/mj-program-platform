import json
import os
import ipaddress
import hmac
from types import SimpleNamespace
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ..internal import internal_json_response, parse_json_body, require_internal_auth
from .session import (
    AuthSessionError,
    build_full_access_employee,
    create_auth_session_token,
    replace_auth_session,
    revoke_auth_session,
    validate_auth_token,
)
from .tokens import delete_auth_cookie, public_token_metadata, set_auth_cookie
from ..dingtalk.client import DingTalkAPIError, login_with_scan_code, login_with_workbench_code
from ..models import Employee
from ..org.revision import advance_organization_revision, lock_organization_state
from ..org.organization_access import can_manage_organization
from ..org.queries import (
    employee_matches_keyword,
    has_full_access_user_id,
    is_pinyin_initial_keyword,
    request_has_full_access_user_id,
)
from .rate_limit import enforce_rate_limit


WORKBENCH_LOGIN_TYPES = {"workbench", "free", "silent"}
DEV_LOGIN_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEV_LOGIN_SECRET_HEADER = "X-Auth-Dev-Login-Secret"


def _is_truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _request_host_is_localhost(request) -> bool:
    raw_host = request.get_host().strip().lower()
    if raw_host.startswith("[") and "]" in raw_host:
        host = raw_host[1:raw_host.index("]")]
    else:
        host = raw_host.split(":", 1)[0]
    return host in DEV_LOGIN_ALLOWED_HOSTS


def _request_client_ip(request) -> ipaddress._BaseAddress | None:
    remote_addr = str(request.META.get("REMOTE_ADDR") or "").strip()
    try:
        remote_ip = ipaddress.ip_address(remote_addr) if remote_addr else None
    except ValueError:
        remote_ip = None

    # When Django is reached directly from a public address, never trust
    # client-supplied forwarding headers for local-dev login decisions.
    if remote_ip is not None and not (remote_ip.is_private or remote_ip.is_loopback or remote_ip.is_link_local):
        return remote_ip

    candidates = []
    forwarded_for = str(request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if forwarded_for:
        candidates.extend([item.strip() for item in forwarded_for.split(",") if item.strip()])
    candidates.append(str(request.META.get("HTTP_X_REAL_IP") or "").strip())
    candidates.append(remote_addr)

    parsed_candidates: list[ipaddress._BaseAddress] = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed_candidates.append(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    for candidate_ip in parsed_candidates:
        if not (candidate_ip.is_private or candidate_ip.is_loopback or candidate_ip.is_link_local):
            return candidate_ip
    if parsed_candidates:
        return parsed_candidates[0]
    return None


def _request_is_local_dev_client(request) -> bool:
    client_ip = _request_client_ip(request)
    if client_ip is None:
        return False
    if client_ip.is_loopback:
        return True
    return bool(settings.DEBUG and _request_host_is_localhost(request) and client_ip.is_private)


def _request_is_trusted_local_docker_client(request) -> bool:
    if not _is_truthy_env("AUTH_DEV_LOGIN_TRUST_PRIVATE_LOCALHOST"):
        return False
    client_ip = _request_client_ip(request)
    if client_ip is None:
        return False
    return bool(_request_host_is_localhost(request) and (client_ip.is_private or client_ip.is_loopback or client_ip.is_link_local))


def _request_has_dev_login_secret(request) -> bool:
    expected_secret = os.getenv("AUTH_DEV_LOGIN_REMOTE_SECRET", "").strip()
    if not expected_secret:
        return False
    provided_secret = str(request.headers.get(DEV_LOGIN_SECRET_HEADER) or "").strip()
    if not provided_secret:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        provided_secret = str(payload.get("devLoginSecret") or "").strip()
    return bool(provided_secret and hmac.compare_digest(provided_secret, expected_secret))


def _dev_login_allowed(request) -> bool:
    if not (_is_truthy_env("AUTH_DEV_LOGIN_ENABLED") or settings.DEBUG):
        return False
    if _is_truthy_env("AUTH_DEV_LOGIN_ALLOW_REMOTE"):
        return _request_has_dev_login_secret(request)
    if _request_is_local_dev_client(request) or _request_is_trusted_local_docker_client(request):
        return True
    if not settings.DEBUG:
        return False
    return False


def _get_first_full_access_user_id() -> str:
    raw_value = os.getenv("FULL_ACCESS_USER_IDS", "")
    normalized_value = raw_value.replace(";", ",").replace("\n", ",")
    return next(
        (
            user_id.strip()
            for user_id in normalized_value.split(",")
            if user_id.strip()
        ),
        "",
    )


def _validate_employee_login(result: dict) -> Optional[JsonResponse]:
    user_id = str(result.get("userId") or "").strip()
    if not user_id:
        return None

    employee = Employee.objects.filter(user_id=user_id).only(
        "user_id",
        "identity_source",
        "status",
        "account_status",
    ).first()
    if employee is None:
        if has_full_access_user_id(user_id):
            return None
        return JsonResponse({"code": "EMPLOYEE_NOT_ALLOWED", "error": "Employee is not synchronized or not allowed"}, status=403)

    if employee.identity_source != Employee.IDENTITY_DINGTALK:
        return JsonResponse({"code": "DINGTALK_ACCOUNT_REQUIRED", "error": "This account cannot sign in with DingTalk"}, status=403)

    if employee.status == Employee.STATUS_INACTIVE:
        return JsonResponse({"error": "Employee is inactive"}, status=403)

    if employee.account_status == Employee.ACCOUNT_DISABLED and not has_full_access_user_id(user_id):
        return JsonResponse({"error": "Account is disabled"}, status=403)

    return None


def _format_user_display(name: str, user_id: str) -> str:
    normalized_name = str(name or "").strip()
    normalized_user_id = str(user_id or "").strip()
    if normalized_name and normalized_user_id:
        return f"{normalized_name} ({normalized_user_id})"
    return normalized_name or normalized_user_id


def _is_known_employee(employee: Optional[Employee]) -> bool:
    if employee is None:
        return False
    state = getattr(employee, "_state", None)
    return not bool(getattr(state, "adding", False))


def _can_proxy_as(user_id: str) -> bool:
    return has_full_access_user_id(user_id)


def _build_session_payload(
    employee: Optional[Employee],
    *,
    token_payload: Optional[dict] = None,
    actor_employee: Optional[Employee] = None,
    avatar_url: str = "",
) -> dict:
    user_id = employee.user_id if employee is not None else ""
    auth_channel = str(
        getattr(employee, "identity_source", "")
        or (token_payload or {}).get("authChannel")
        or Employee.IDENTITY_DINGTALK
    )
    actor_user_id = actor_employee.user_id if actor_employee is not None else user_id
    is_proxying = bool(actor_employee is not None and actor_user_id and actor_user_id != user_id)
    is_full_access_user = bool(
        auth_channel == Employee.IDENTITY_DINGTALK
        and has_full_access_user_id(user_id)
    )
    can_manage_platform_settings = can_manage_organization(SimpleNamespace(
        auth_user_id=user_id, auth_employee=employee, auth_is_proxy=is_proxying,
    ))
    can_start_proxy = bool(is_full_access_user and not is_proxying)
    effective_avatar_url = str(
        avatar_url
        or (employee.avatar_url if employee is not None and getattr(employee, "avatar_url", "") else "")
        or ""
    ).strip()
    payload = {
        "knownEmployee": _is_known_employee(employee),
        "userId": user_id,
        "name": employee.name if employee is not None else "",
        "nick": employee.name if employee is not None else "",
        "avatarUrl": effective_avatar_url,
        "status": employee.status if employee is not None else "",
        "accountStatus": employee.account_status if employee is not None else "",
        "isSystemAdmin": is_full_access_user,
        "canUseSystemAdmin": is_full_access_user,
        "isFullAccessUser": is_full_access_user,
        "canManagePlatformSettings": can_manage_platform_settings,
        "canConfigurePermissions": can_manage_platform_settings,
        "canManageEmployeeAccountStatus": can_manage_platform_settings,
        "canSyncContacts": can_manage_platform_settings,
        "canAccessInactiveEmployees": can_manage_platform_settings,
        "authVersion": employee.auth_version if employee is not None else 1,
        "authChannel": auth_channel,
        "canProxy": auth_channel == Employee.IDENTITY_DINGTALK and can_start_proxy,
        "canStartProxy": can_start_proxy,
        "canSwitchProxy": False,
        "isProxying": is_proxying,
        "actorUserId": actor_user_id,
        "actorName": actor_employee.name if actor_employee is not None else (employee.name if employee is not None else ""),
        "actorAvatarUrl": (
            str(getattr(actor_employee, "avatar_url", "") or "").strip()
            if actor_employee is not None
            else effective_avatar_url
        ),
        "actorDisplay": _format_user_display(
            actor_employee.name if actor_employee is not None else (employee.name if employee is not None else ""),
            actor_user_id,
        ),
    }
    if token_payload:
        payload.update(token_payload)
    return payload


@require_GET
def auth_session_validate(request):
    user_id = str(getattr(request, "auth_user_id", "") or "").strip()
    if not user_id:
        return JsonResponse({"error": "Invalid login session"}, status=401)

    employee = getattr(request, "auth_employee", None)
    actor_employee = getattr(request, "auth_actor_employee", None)
    if employee is None:
        actor_user_id = str(getattr(request, "auth_actor_user_id", "") or user_id).strip()
        claims = getattr(request, "auth_token_claims", {}) or {}
        is_full_access_user = has_full_access_user_id(user_id)
        is_proxying = actor_user_id != user_id
        can_manage_platform_settings = is_full_access_user
        can_start_proxy = bool(is_full_access_user and not is_proxying)
        return JsonResponse(
            {
                "ok": True,
                "knownEmployee": False,
                "sessionId": str(claims.get("sid") or ""),
                "userId": user_id,
                "avatarUrl": str(claims.get("au") or "").strip(),
                "isSystemAdmin": is_full_access_user,
                "canUseSystemAdmin": is_full_access_user,
                "isFullAccessUser": is_full_access_user,
                "canManagePlatformSettings": can_manage_platform_settings,
                "canConfigurePermissions": can_manage_platform_settings,
                "canManageEmployeeAccountStatus": can_manage_platform_settings,
                "canSyncContacts": can_manage_platform_settings,
                "canAccessInactiveEmployees": can_manage_platform_settings,
                "canProxy": can_start_proxy,
                "canStartProxy": can_start_proxy,
                "canSwitchProxy": False,
                "isProxying": is_proxying,
                "actorUserId": actor_user_id,
                "actorDisplay": actor_user_id,
            }
        )

    claims = getattr(request, "auth_token_claims", {}) or {}
    return JsonResponse(
        {
            "ok": True,
            "knownEmployee": True,
            "sessionId": str(claims.get("sid") or ""),
            **_build_session_payload(employee, actor_employee=actor_employee),
        }
    )


@csrf_exempt
@require_POST
def auth_logout(request):
    session = getattr(request, "auth_session", None)
    if session is not None:
        revoke_auth_session(session)
    response = JsonResponse({"ok": True})
    delete_auth_cookie(response)
    return response


@csrf_exempt
@require_POST
def auth_token_introspect(request):
    secret_error = require_internal_auth(request, service_name="Auth introspection")
    if secret_error is not None:
        return secret_error

    payload = parse_json_body(request)
    token = str(payload.get("token") or "").strip()
    if not token:
        return internal_json_response(
            request,
            {"ok": False, "error": "Missing auth token"},
            status=400,
            code="MISSING_AUTH_TOKEN",
        )

    try:
        session = validate_auth_token(token)
    except AuthSessionError as exc:
        return internal_json_response(
            request,
            {"ok": False, "error": str(exc)},
            status=exc.status_code,
            code=exc.code,
        )

    return JsonResponse(
        {
            "ok": True,
            **_build_session_payload(session.employee, actor_employee=session.actor_employee),
            "userId": session.user_id,
            "actorUserId": session.actor_user_id,
            "isProxying": session.is_proxy,
            "claims": session.claims,
        }
    )


@csrf_exempt
@require_POST
def auth_internal_service_validate(request):
    secret_error = require_internal_auth(request, service_name="Internal service validation")
    if secret_error is not None:
        return secret_error
    return internal_json_response(
        request,
        {
            "serviceName": request.internal_caller,
            "appId": request.internal_service_app_id,
        },
    )


@csrf_exempt
@require_POST
def auth_code(request):
    rate_limit_response = enforce_rate_limit(request, scope="auth-code", limit=30, window_seconds=60)
    if rate_limit_response is not None:
        return rate_limit_response
    payload = parse_json_body(request)
    auth_code_value = str(payload.get("authCode") or payload.get("code") or "").strip()
    if not auth_code_value:
        return JsonResponse({"code": "MISSING_AUTH_CODE", "error": "Missing authCode"}, status=400)

    login_type = str(payload.get("loginType") or payload.get("mode") or "scan").strip().lower()

    try:
        if login_type in WORKBENCH_LOGIN_TYPES:
            result = login_with_workbench_code(auth_code_value)
        else:
            result = login_with_scan_code(auth_code_value)
    except DingTalkAPIError as exc:
        return JsonResponse(
            {"ok": False, "code": "DINGTALK_API_ERROR", "error": str(exc)},
            status=exc.status,
        )

    blocked_response = _validate_employee_login(result)
    if blocked_response is not None:
        return blocked_response

    user_id = str(result.get("userId") or "").strip()
    if not user_id:
        return JsonResponse({"error": "DingTalk login did not return userId"}, status=502)

    login_avatar_url = str(result.get("avatarUrl") or result.get("avatar") or result.get("avatar_url") or "").strip()
    employee = Employee.objects.filter(
        user_id=user_id,
        identity_source=Employee.IDENTITY_DINGTALK,
    ).first()
    if employee is not None and login_avatar_url and employee.avatar_url != login_avatar_url:
        with transaction.atomic():
            organization_state = lock_organization_state()
            employee = Employee.objects.select_for_update().get(
                user_id=user_id,
                identity_source=Employee.IDENTITY_DINGTALK,
            )
            if employee.avatar_url != login_avatar_url:
                employee.avatar_url = login_avatar_url
                employee.save(update_fields=["avatar_url", "updated_at"])
                advance_organization_revision(state=organization_state)
    auth_version = employee.auth_version if employee is not None else 1
    session_employee = employee or Employee(
        user_id=user_id,
        name=str(result.get("name") or result.get("nick") or user_id),
        avatar_url=login_avatar_url,
        auth_version=auth_version,
    )
    token_payload = create_auth_session_token(session_employee)
    response = JsonResponse(
        {
            **result,
            **public_token_metadata(token_payload),
            **_build_session_payload(
                session_employee,
                avatar_url=login_avatar_url,
            ),
        }
    )
    set_auth_cookie(response, token_payload)
    return response


@csrf_exempt
@require_POST
def auth_dev_login(request):
    rate_limit_response = enforce_rate_limit(request, scope="dev-login", limit=10, window_seconds=60)
    if rate_limit_response is not None:
        return rate_limit_response
    if not _dev_login_allowed(request):
        return JsonResponse(
            {
                "code": "DEV_LOGIN_DISABLED",
                "error": "Local dev login is disabled",
            },
            status=404,
        )

    user_id = _get_first_full_access_user_id()
    if not user_id:
        return JsonResponse(
            {
                "code": "DEV_LOGIN_MISSING_FULL_ACCESS_USER",
                "error": "Local dev login needs FULL_ACCESS_USER_IDS to contain at least one userId",
            },
            status=400,
        )

    employee = Employee.objects.filter(
        user_id=user_id,
        identity_source=Employee.IDENTITY_DINGTALK,
    ).first()
    if employee is not None:
        denied = _validate_employee_login({"userId": user_id})
        if denied is not None:
            return denied
    session_employee = employee or build_full_access_employee(user_id) or Employee(
        user_id=user_id,
        name=user_id,
        status=Employee.STATUS_ACTIVE,
        account_status=Employee.ACCOUNT_ENABLED,
        auth_version=1,
    )
    token_payload = create_auth_session_token(session_employee)
    response = JsonResponse(
        {
            "ok": True,
            "loginType": "dev",
            "reason": "local-full-access-login",
            **public_token_metadata(token_payload),
            **_build_session_payload(session_employee),
        }
    )
    set_auth_cookie(response, token_payload)
    return response


@require_GET
def auth_proxy_candidates(request):
    if getattr(request, "auth_is_proxy", False):
        return JsonResponse({"code": "PROXY_NESTING_FORBIDDEN", "error": "代理状态下不能再次代理"}, status=403)
    actor_user_id = str(getattr(request, "auth_actor_user_id", "") or getattr(request, "auth_user_id", "")).strip()
    if not _can_proxy_as(actor_user_id):
        return JsonResponse({"error": "Current account cannot proxy"}, status=403)

    keyword = str(request.GET.get("keyword") or "").strip()
    queryset = Employee.objects.filter(
        identity_source=Employee.IDENTITY_DINGTALK,
        status=Employee.STATUS_ACTIVE,
        account_status=Employee.ACCOUNT_ENABLED,
    ).order_by("user_id")
    try:
        limit = min(max(int(request.GET.get("limit") or 50), 1), 100)
    except (TypeError, ValueError):
        return JsonResponse({"error": "limit must be an integer"}, status=400)
    if keyword and not is_pinyin_initial_keyword(keyword):
        queryset = queryset.filter(Q(name__icontains=keyword) | Q(user_id__icontains=keyword))
    employees = list(queryset)
    if keyword and is_pinyin_initial_keyword(keyword):
        employees = [employee for employee in employees if employee_matches_keyword(employee, keyword)]
    total = len(employees)
    employees = employees[:limit]
    items = [
        {
            "userId": item.user_id,
            "name": item.name,
            "displayName": _format_user_display(item.name, item.user_id),
        }
        for item in employees
    ]
    return JsonResponse({"keyword": keyword, "limit": limit, "total": total, "count": len(items), "items": items})


@csrf_exempt
@require_POST
def auth_proxy_start(request):
    if getattr(request, "auth_is_proxy", False):
        return JsonResponse({"code": "PROXY_NESTING_FORBIDDEN", "error": "代理状态下不能再次代理"}, status=403)
    actor_user_id = str(getattr(request, "auth_actor_user_id", "") or getattr(request, "auth_user_id", "")).strip()
    current_user_id = str(getattr(request, "auth_user_id", "") or "").strip()
    claims = getattr(request, "auth_token_claims", {}) or {}
    actor_employee = (
        getattr(request, "auth_actor_employee", None)
        or Employee.objects.filter(
            user_id=actor_user_id,
            identity_source=Employee.IDENTITY_DINGTALK,
        ).first()
        or build_full_access_employee(actor_user_id, claims.get("aav") or claims.get("av") or 1)
    )
    if not _can_proxy_as(actor_user_id):
        return JsonResponse({"error": "Current account cannot proxy"}, status=403)

    target_user_id = str(request.POST.get("userId") or "").strip()
    if not target_user_id:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
            target_user_id = str(payload.get("userId") or "").strip()
        except Exception:
            target_user_id = target_user_id.strip()
    if not target_user_id:
        return JsonResponse({"error": "Missing target userId"}, status=400)
    if target_user_id == current_user_id:
        return JsonResponse({"error": "Already using this account"}, status=400)
    if target_user_id == actor_user_id:
        return JsonResponse({"error": "Use stop proxy instead"}, status=400)

    target_employee = Employee.objects.filter(
        user_id=target_user_id,
        identity_source=Employee.IDENTITY_DINGTALK,
    ).first()
    if target_employee is None:
        return JsonResponse({"error": f"Employee not found: {target_user_id}"}, status=404)
    if target_employee.status != Employee.STATUS_ACTIVE:
        return JsonResponse({"error": "Inactive employee cannot be proxied"}, status=400)
    if target_employee.account_status != Employee.ACCOUNT_ENABLED:
        return JsonResponse({"error": "Disabled account cannot be proxied"}, status=400)
    if actor_employee is None:
        return JsonResponse({"error": "Proxy actor not found"}, status=401)

    current_session = getattr(request, "auth_session", None)
    if current_session is None:
        return JsonResponse({"error": "Current login session was not found"}, status=401)
    try:
        token_payload = replace_auth_session(
            current_session,
            target_employee,
            actor_employee=actor_employee,
            reason="proxy_start",
        )
    except AuthSessionError as exc:
        return JsonResponse({"code": exc.code, "error": str(exc)}, status=exc.status_code)
    response = JsonResponse(
        {
            "ok": True,
            **_build_session_payload(
                target_employee,
                token_payload=public_token_metadata(token_payload),
                actor_employee=actor_employee,
            ),
        }
    )
    set_auth_cookie(response, token_payload)
    return response


@csrf_exempt
@require_POST
def auth_proxy_stop(request):
    if not getattr(request, "auth_is_proxy", False):
        return JsonResponse({"error": "Not proxying"}, status=400)

    actor_employee = getattr(request, "auth_actor_employee", None)
    if actor_employee is None:
        return JsonResponse({"error": "Proxy actor not found"}, status=401)

    try:
        token_payload = replace_auth_session(
            request.auth_session,
            actor_employee,
            actor_employee=actor_employee,
            reason="proxy_stop",
        )
    except AuthSessionError as exc:
        return JsonResponse({"code": exc.code, "error": str(exc)}, status=exc.status_code)
    response = JsonResponse(
        {
            "ok": True,
            **_build_session_payload(
                actor_employee,
                token_payload=public_token_metadata(token_payload),
                actor_employee=actor_employee,
            ),
        }
    )
    set_auth_cookie(response, token_payload)
    return response
