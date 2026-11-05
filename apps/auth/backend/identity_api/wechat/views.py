from __future__ import annotations

from datetime import timedelta
import hashlib
import ipaddress
import os
import secrets
import uuid

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods

from ..auth.rate_limit import enforce_rate_limit
from ..auth.session import create_auth_session_token, refresh_auth_token
from ..auth.tokens import AUTH_CHANNEL_WECHAT_MINI, AuthTokenError
from ..internal import parse_json_body
from ..models import (
    AuthSession,
    Employee,
    WeChatMiniIdentity,
    WeChatMiniRegistrationChallenge,
)
from .client import WeChatMiniAPIError, configured_app_id, exchange_login_code


PRIVACY_VERSION = "2026-09-15"
DEFAULT_CHALLENGE_TTL_SECONDS = 10 * 60


def _error(message: str, *, status: int, code: str) -> JsonResponse:
    return JsonResponse({"ok": False, "code": code, "error": message}, status=status)


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _challenge_ttl_seconds() -> int:
    try:
        value = int(os.getenv("WECHAT_MINI_REGISTRATION_TTL_SECONDS", str(DEFAULT_CHALLENGE_TTL_SECONDS)))
    except (TypeError, ValueError):
        value = DEFAULT_CHALLENGE_TTL_SECONDS
    return min(max(value, 300), 1800)


def _token_digest(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _mini_session_payload(employee: Employee, token_payload: dict) -> dict:
    return {
        **token_payload,
        "authChannel": AUTH_CHANNEL_WECHAT_MINI,
        "user": {
            "userId": employee.user_id,
            "name": employee.name,
            "avatarUrl": employee.avatar_url,
        },
    }


def _employee_login_error(employee: Employee) -> JsonResponse | None:
    if employee.identity_source != Employee.IDENTITY_WECHAT_MINI:
        return _error("账号登录渠道不匹配", status=403, code="AUTH_CHANNEL_MISMATCH")
    if employee.status == Employee.STATUS_INACTIVE or employee.account_status == Employee.ACCOUNT_DISABLED:
        return _error("该微信账号已注销或停用", status=403, code="WECHAT_ACCOUNT_DISABLED")
    return None


def _issue_login(identity: WeChatMiniIdentity) -> JsonResponse:
    employee = identity.employee
    failure = _employee_login_error(employee)
    if failure is not None:
        return failure
    token_payload = create_auth_session_token(employee)
    return JsonResponse(_mini_session_payload(employee, token_payload))


def _registration_challenge(app_id: str, openid: str, unionid: str) -> JsonResponse:
    raw_token = secrets.token_urlsafe(32)
    ttl_seconds = _challenge_ttl_seconds()
    now = timezone.now()
    expires_at = now + timedelta(seconds=ttl_seconds)
    WeChatMiniRegistrationChallenge.objects.filter(expires_at__lte=now).delete()
    WeChatMiniRegistrationChallenge.objects.create(
        token_digest=_token_digest(raw_token),
        app_id=app_id,
        openid=openid,
        unionid=unionid,
        expires_at=expires_at,
    )
    return JsonResponse(
        {
            "ok": True,
            "registrationRequired": True,
            "registrationToken": raw_token,
            "expiresAt": expires_at.isoformat(),
            "expiresIn": ttl_seconds,
            "privacyVersion": PRIVACY_VERSION,
        }
    )


def _login_identity(app_id: str, openid: str, unionid: str) -> JsonResponse:
    identity = WeChatMiniIdentity.objects.select_related("employee").filter(
        app_id=app_id,
        openid=openid,
    ).first()
    if identity is None:
        return _registration_challenge(app_id, openid, unionid)

    identity.last_login_at = timezone.now()
    update_fields = ["last_login_at", "updated_at"]
    if unionid and identity.unionid != unionid:
        identity.unionid = unionid
        update_fields.append("unionid")
    identity.save(update_fields=update_fields)
    return _issue_login(identity)


@csrf_exempt
@require_POST
def wechat_mini_login(request):
    limited = enforce_rate_limit(request, scope="wechat-mini-login", limit=30, window_seconds=60)
    if limited is not None:
        return limited
    payload = parse_json_body(request)
    code = str(payload.get("code") or "").strip()
    if not code:
        return _error("缺少微信登录凭证", status=400, code="WECHAT_LOGIN_CODE_REQUIRED")
    try:
        identity = exchange_login_code(code)
    except WeChatMiniAPIError as exc:
        return _error(str(exc), status=exc.status, code=exc.code)
    return _login_identity(identity["app_id"], identity["openid"], identity["unionid"])


def _request_is_local(request) -> bool:
    remote_addr = str(request.META.get("REMOTE_ADDR") or "").strip()
    try:
        remote_ip = ipaddress.ip_address(remote_addr)
    except ValueError:
        return False
    return bool(remote_ip.is_private or remote_ip.is_loopback or remote_ip.is_link_local)


@csrf_exempt
@require_POST
def wechat_mini_dev_login(request):
    limited = enforce_rate_limit(request, scope="wechat-mini-dev-login", limit=10, window_seconds=60)
    if limited is not None:
        return limited
    if not settings.DEBUG or not _truthy_env("WECHAT_MINI_DEV_LOGIN_ENABLED") or not _request_is_local(request):
        return _error("微信开发登录未启用", status=404, code="WECHAT_DEV_LOGIN_DISABLED")
    app_id = configured_app_id() or "dev-wechat-mini"
    openid = os.getenv("WECHAT_MINI_DEV_OPENID", "dev-openid").strip() or "dev-openid"
    return _login_identity(app_id, openid, "")


@csrf_exempt
@require_POST
def wechat_mini_register(request):
    limited = enforce_rate_limit(request, scope="wechat-mini-register", limit=15, window_seconds=60)
    if limited is not None:
        return limited
    payload = parse_json_body(request)
    raw_token = str(payload.get("registrationToken") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not raw_token or len(raw_token) > 256:
        return _error("缺少注册凭证", status=400, code="WECHAT_REGISTRATION_TOKEN_REQUIRED")
    if not name or len(name) > 128:
        return _error("姓名不能为空且不能超过 128 个字符", status=400, code="WECHAT_NAME_INVALID")
    if payload.get("privacyAccepted") is not True or payload.get("privacyVersion") != PRIVACY_VERSION:
        return _error("请先阅读并同意用户协议和隐私保护指引", status=400, code="PRIVACY_CONSENT_REQUIRED")

    now = timezone.now()
    try:
        with transaction.atomic():
            challenge = WeChatMiniRegistrationChallenge.objects.select_for_update().filter(
                token_digest=_token_digest(raw_token),
            ).first()
            if challenge is None or challenge.used_at is not None or challenge.expires_at <= now:
                return _error("注册凭证已失效，请重新进入小程序", status=401, code="WECHAT_REGISTRATION_TOKEN_INVALID")

            identity = WeChatMiniIdentity.objects.select_related("employee").filter(
                app_id=challenge.app_id,
                openid=challenge.openid,
            ).first()
            if identity is None:
                employee = Employee.objects.create(
                    user_id=f"wxmini:{uuid.uuid4().hex}",
                    identity_source=Employee.IDENTITY_WECHAT_MINI,
                    name=name,
                    status=Employee.STATUS_ACTIVE,
                    account_status=Employee.ACCOUNT_ENABLED,
                    create_time=now,
                )
                identity = WeChatMiniIdentity.objects.create(
                    app_id=challenge.app_id,
                    openid=challenge.openid,
                    unionid=challenge.unionid,
                    employee=employee,
                    privacy_version=PRIVACY_VERSION,
                    privacy_agreed_at=now,
                    last_login_at=now,
                )
            else:
                failure = _employee_login_error(identity.employee)
                if failure is not None:
                    return failure
                employee = identity.employee

            challenge.used_at = now
            challenge.save(update_fields=["used_at"])
    except IntegrityError:
        return _error("微信账号注册冲突，请重新登录", status=409, code="WECHAT_REGISTRATION_CONFLICT")

    token_payload = create_auth_session_token(employee)
    return JsonResponse(_mini_session_payload(employee, token_payload), status=201)


def _require_wechat_session(request):
    claims = getattr(request, "auth_token_claims", {}) or {}
    if claims.get("chn") != AUTH_CHANNEL_WECHAT_MINI or claims.get("aud") != "after-sales-mobile":
        return _error("该接口仅供微信小程序账号使用", status=403, code="WECHAT_ACCOUNT_REQUIRED")
    return None


@csrf_exempt
@require_POST
def wechat_mini_refresh(request):
    failure = _require_wechat_session(request)
    if failure is not None:
        return failure
    session = getattr(request, "auth_session", None)
    employee = getattr(request, "auth_employee", None)
    if session is None or employee is None:
        return _error("登录已失效", status=401, code="INVALID_AUTH_TOKEN")
    try:
        token_payload = refresh_auth_token(session)
    except AuthTokenError as exc:
        return _error(str(exc), status=401, code="INVALID_AUTH_TOKEN")
    return JsonResponse(_mini_session_payload(employee, token_payload))


@csrf_exempt
@require_http_methods(["DELETE"])
def wechat_mini_account(request):
    failure = _require_wechat_session(request)
    if failure is not None:
        return failure
    user_id = str(getattr(request, "auth_user_id", "") or "").strip()
    now = timezone.now()
    with transaction.atomic():
        identity = WeChatMiniIdentity.objects.select_for_update().filter(employee_id=user_id).first()
        if identity is None:
            return _error("微信账号不存在或已注销", status=404, code="WECHAT_ACCOUNT_NOT_FOUND")
        app_id = identity.app_id
        openid = identity.openid
        identity.delete()
        WeChatMiniRegistrationChallenge.objects.filter(app_id=app_id, openid=openid).delete()
        Employee.objects.filter(user_id=user_id).update(
            name="已注销微信用户",
            avatar_url="",
            status=Employee.STATUS_INACTIVE,
            account_status=Employee.ACCOUNT_DISABLED,
            handover_user_id="",
            auth_version=F("auth_version") + 1,
            updated_at=now,
        )
        AuthSession.objects.filter(
            user_id=user_id,
            status=AuthSession.STATUS_ACTIVE,
        ).update(
            status=AuthSession.STATUS_REVOKED,
            revoked_at=now,
            revoke_reason="account_deleted",
            updated_at=now,
        )
    return JsonResponse(
        {
            "ok": True,
            "message": "微信账号和登录身份已注销；依法需要留存的历史服务记录将继续保留。",
        }
    )
