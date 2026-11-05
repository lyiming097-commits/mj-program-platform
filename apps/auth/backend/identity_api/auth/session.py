from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone
import os
import time
from typing import Any

from django.db import transaction
from django.utils import timezone

from ..models import AuthSession as AuthSessionRecord, Employee
from ..org.queries import has_full_access_user_id
from .tokens import (
    AUDIENCE_AFTER_SALES_MOBILE,
    AUDIENCE_PLATFORM,
    AUTH_CHANNEL_DINGTALK,
    AUTH_CHANNEL_WECHAT_MINI,
    AuthTokenError,
    decode_auth_token,
    issue_auth_token,
)
from .tokens import _get_session_max_age_seconds


@dataclass(frozen=True)
class AuthSession:
    claims: dict[str, Any]
    user_id: str
    employee: Employee | None
    actor_user_id: str
    actor_employee: Employee | None
    record: AuthSessionRecord

    @property
    def is_proxy(self) -> bool:
        return self.actor_user_id != self.user_id


class AuthSessionError(Exception):
    def __init__(self, message: str, status_code: int = 401, code: str = "INVALID_AUTH_TOKEN"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def build_full_access_employee(user_id: str, auth_version: int = 1, display_name: str = "") -> Employee | None:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id or not has_full_access_user_id(normalized_user_id):
        return None
    normalized_display_name = str(display_name or "").strip()
    display_name = normalized_display_name or os.getenv("AUTH_DEV_LOGIN_NAME", "").strip() or normalized_user_id
    return Employee(
        user_id=normalized_user_id,
        name=display_name,
        status=Employee.STATUS_ACTIVE,
        account_status=Employee.ACCOUNT_ENABLED,
        auth_version=max(int(auth_version or 1), 1),
        identity_source=Employee.IDENTITY_DINGTALK,
    )


def _account_disabled_blocks(employee: Employee | None) -> bool:
    return bool(
        employee is not None
        and employee.account_status == Employee.ACCOUNT_DISABLED
        and not (
            employee.identity_source == Employee.IDENTITY_DINGTALK
            and has_full_access_user_id(employee.user_id)
        )
    )


def validate_auth_token(token: str) -> AuthSession:
    try:
        claims = decode_auth_token(token)
    except AuthTokenError as exc:
        raise AuthSessionError(str(exc), 401, "INVALID_AUTH_TOKEN") from exc

    user_id = str(claims["sub"]).strip()
    actor_user_id = str(claims.get("act") or user_id).strip()
    session_record = AuthSessionRecord.objects.filter(session_id=claims["sid"]).first()
    if session_record is None:
        raise AuthSessionError("Login session does not exist. Please sign in again.", 401, "AUTH_SESSION_NOT_FOUND")
    if session_record.status != AuthSessionRecord.STATUS_ACTIVE or session_record.expires_at <= timezone.now():
        raise AuthSessionError("Login session has been signed out. Please sign in again.", 401, "AUTH_SESSION_REVOKED")
    if (
        session_record.user_id != user_id
        or session_record.actor_user_id != actor_user_id
        or session_record.session_started_at != claims["sai"]
    ):
        raise AuthSessionError("Login session does not match this token.", 401, "AUTH_SESSION_MISMATCH")

    employee = Employee.objects.filter(user_id=user_id).only(
        "user_id",
        "name",
        "avatar_url",
        "status",
        "account_status",
        "auth_version",
        "identity_source",
    ).first()
    if employee is None:
        employee = build_full_access_employee(user_id, claims["av"], str(claims.get("dn") or ""))
        if employee is None:
            raise AuthSessionError("Employee is not synchronized or not allowed", 403, "EMPLOYEE_NOT_ALLOWED")

    if actor_user_id == user_id:
        actor_employee = employee
    else:
        actor_employee = Employee.objects.filter(user_id=actor_user_id).only(
            "user_id",
            "name",
            "avatar_url",
            "status",
            "account_status",
            "auth_version",
            "identity_source",
        ).first()
        if actor_employee is None:
            actor_employee = build_full_access_employee(actor_user_id, claims.get("aav", 1), str(claims.get("adn") or ""))

    if employee.status == Employee.STATUS_INACTIVE:
        raise AuthSessionError("Employee is inactive", 403, "EMPLOYEE_INACTIVE")
    if _account_disabled_blocks(employee):
        raise AuthSessionError("Account is disabled", 403, "ACCOUNT_DISABLED")
    if employee.auth_version != claims["av"]:
        raise AuthSessionError("Login session is invalid. Please sign in again.", 401, "AUTH_VERSION_MISMATCH")
    if employee.identity_source != claims["chn"]:
        raise AuthSessionError("Login channel does not match this account.", 401, "AUTH_CHANNEL_MISMATCH")

    if actor_user_id != user_id:
        if claims["chn"] != AUTH_CHANNEL_DINGTALK:
            raise AuthSessionError("WeChat accounts cannot use proxy sessions.", 403, "PROXY_CHANNEL_FORBIDDEN")
        if not has_full_access_user_id(actor_user_id):
            raise AuthSessionError(
                "Proxy actor is no longer a system administrator. Please sign in again.",
                403,
                "PROXY_ACTOR_NOT_SYSTEM_ADMIN",
            )
        if actor_employee is None:
            raise AuthSessionError("Proxy actor does not exist. Please sign in again.", 401, "PROXY_ACTOR_NOT_FOUND")
        if actor_employee.status == Employee.STATUS_INACTIVE:
            raise AuthSessionError("Proxy actor is inactive. Please sign in again.", 403, "PROXY_ACTOR_INACTIVE")
        if _account_disabled_blocks(actor_employee):
            raise AuthSessionError("Proxy actor account is disabled. Please sign in again.", 403, "PROXY_ACTOR_ACCOUNT_DISABLED")
        if actor_employee.auth_version != claims.get("aav"):
            raise AuthSessionError("Proxy session is invalid. Please sign in again.", 401, "PROXY_AUTH_VERSION_MISMATCH")
        if actor_employee.identity_source != Employee.IDENTITY_DINGTALK:
            raise AuthSessionError("Proxy actor must be a DingTalk account.", 403, "PROXY_CHANNEL_FORBIDDEN")

    return AuthSession(
        claims=claims,
        user_id=user_id,
        employee=employee,
        actor_user_id=actor_user_id,
        actor_employee=actor_employee,
        record=session_record,
    )


def _session_expiry(session_started_at: int) -> datetime:
    expires_at_timestamp = int(session_started_at) + _get_session_max_age_seconds()
    return datetime.fromtimestamp(expires_at_timestamp, tz=datetime_timezone.utc)


def create_auth_session_token(
    employee: Employee,
    *,
    actor_employee: Employee | None = None,
    session_started_at: int | None = None,
    audience: str | None = None,
) -> dict[str, Any]:
    actor = actor_employee or employee
    auth_channel = str(getattr(employee, "identity_source", "") or Employee.IDENTITY_DINGTALK)
    if actor.user_id != employee.user_id and (
        auth_channel != AUTH_CHANNEL_DINGTALK
        or getattr(actor, "identity_source", Employee.IDENTITY_DINGTALK) != Employee.IDENTITY_DINGTALK
    ):
        raise AuthTokenError("Only DingTalk accounts can use proxy sessions")
    resolved_audience = audience or (
        AUDIENCE_AFTER_SALES_MOBILE
        if auth_channel == AUTH_CHANNEL_WECHAT_MINI
        else AUDIENCE_PLATFORM
    )
    started_at = int(session_started_at or time.time())
    started_at = min(started_at, int(time.time()))
    expires_at = _session_expiry(started_at)
    if expires_at <= timezone.now():
        raise AuthTokenError("登录会话已达到最大有效期，请重新登录")

    with transaction.atomic():
        session_record = AuthSessionRecord.objects.create(
            user_id=employee.user_id,
            actor_user_id=actor.user_id,
            session_started_at=started_at,
            expires_at=expires_at,
        )
        return issue_auth_token(
            employee.user_id,
            employee.auth_version,
            session_id=session_record.session_id,
            actor_user_id=actor.user_id if actor.user_id != employee.user_id else None,
            actor_auth_version=actor.auth_version if actor.user_id != employee.user_id else None,
            avatar_url=employee.avatar_url,
            display_name=employee.name,
            session_started_at=started_at,
            auth_channel=auth_channel,
            audience=resolved_audience,
        )


def replace_auth_session(
    current_session: AuthSession,
    employee: Employee,
    *,
    actor_employee: Employee | None = None,
    reason: str,
) -> dict[str, Any]:
    actor = actor_employee or employee
    with transaction.atomic():
        current_record = AuthSessionRecord.objects.select_for_update().filter(
            session_id=current_session.record.session_id,
        ).first()
        if current_record is None or current_record.status != AuthSessionRecord.STATUS_ACTIVE:
            raise AuthSessionError("Login session has already changed. Please retry.", 409, "AUTH_SESSION_CHANGED")

        current_record.status = AuthSessionRecord.STATUS_REVOKED
        current_record.revoked_at = timezone.now()
        current_record.revoke_reason = str(reason or "replaced")[:64]
        current_record.save(update_fields=["status", "revoked_at", "revoke_reason", "updated_at"])

        new_record = AuthSessionRecord.objects.create(
            user_id=employee.user_id,
            actor_user_id=actor.user_id,
            session_started_at=current_session.claims["sai"],
            expires_at=_session_expiry(current_session.claims["sai"]),
        )
        return issue_auth_token(
            employee.user_id,
            employee.auth_version,
            session_id=new_record.session_id,
            actor_user_id=actor.user_id if actor.user_id != employee.user_id else None,
            actor_auth_version=actor.auth_version if actor.user_id != employee.user_id else None,
            avatar_url=employee.avatar_url,
            display_name=employee.name,
            session_started_at=current_session.claims["sai"],
            auth_channel=current_session.claims["chn"],
            audience=current_session.claims["aud"],
        )


def revoke_auth_session(session: AuthSession, *, reason: str = "logout") -> None:
    AuthSessionRecord.objects.filter(
        session_id=session.record.session_id,
        status=AuthSessionRecord.STATUS_ACTIVE,
    ).update(
        status=AuthSessionRecord.STATUS_REVOKED,
        revoked_at=timezone.now(),
        revoke_reason=str(reason or "logout")[:64],
        updated_at=timezone.now(),
    )


def refresh_auth_token(session: AuthSession) -> dict[str, Any]:
    if not AuthSessionRecord.objects.filter(
        session_id=session.record.session_id,
        status=AuthSessionRecord.STATUS_ACTIVE,
        expires_at__gt=timezone.now(),
    ).exists():
        raise AuthTokenError("登录会话已发生变化，请使用最新身份")
    return issue_auth_token(
        session.user_id,
        session.claims["av"],
        session_id=session.record.session_id,
        actor_user_id=session.actor_user_id if session.is_proxy else None,
        actor_auth_version=session.claims.get("aav") if session.is_proxy else None,
        avatar_url=str(session.claims.get("au") or "").strip(),
        display_name=str(getattr(session.employee, "name", "") or session.claims.get("dn") or "").strip(),
        session_started_at=session.claims["sai"],
        auth_channel=session.claims["chn"],
        audience=session.claims["aud"],
    )


def bind_auth_session_to_request(request, session: AuthSession) -> None:
    request.auth_session = session
    request.auth_user_id = session.user_id
    request.auth_employee = session.employee
    request.auth_actor_user_id = session.actor_user_id
    request.auth_actor_employee = session.actor_employee
    request.auth_is_proxy = session.is_proxy
    request.auth_token_claims = session.claims
