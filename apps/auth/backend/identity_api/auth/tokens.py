import base64
import binascii
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from django.conf import settings


DEFAULT_TOKEN_TTL_SECONDS = 30 * 60
DEFAULT_SESSION_MAX_AGE_SECONDS = 12 * 60 * 60
DEFAULT_TOKEN_CLOCK_LEEWAY_SECONDS = 30
MAX_TOKEN_LENGTH = 4096
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "mj_auth_token")
AUTH_CHANNEL_DINGTALK = "dingtalk"
AUTH_CHANNEL_WECHAT_MINI = "wechat-mini"
AUDIENCE_PLATFORM = "platform"
AUDIENCE_AFTER_SALES_MOBILE = "after-sales-mobile"
VALID_CHANNEL_AUDIENCES = {
    (AUTH_CHANNEL_DINGTALK, AUDIENCE_PLATFORM),
    (AUTH_CHANNEL_WECHAT_MINI, AUDIENCE_AFTER_SALES_MOBILE),
}


class AuthTokenError(Exception):
    pass


def _get_token_secret() -> bytes:
    secret = os.getenv("AUTH_TOKEN_SECRET", "").strip() or settings.SECRET_KEY
    return secret.encode("utf-8")


def _get_positive_int_env(name: str, default_value: int, *, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default_value)) or default_value)
    except (TypeError, ValueError):
        return default_value
    return max(value, minimum)


def _get_token_ttl_seconds() -> int:
    return _get_positive_int_env("AUTH_TOKEN_TTL_SECONDS", DEFAULT_TOKEN_TTL_SECONDS, minimum=60)


def _get_session_max_age_seconds() -> int:
    return _get_positive_int_env("AUTH_SESSION_MAX_AGE_SECONDS", DEFAULT_SESSION_MAX_AGE_SECONDS, minimum=300)


def _get_token_clock_leeway_seconds() -> int:
    return _get_positive_int_env("AUTH_TOKEN_CLOCK_LEEWAY_SECONDS", DEFAULT_TOKEN_CLOCK_LEEWAY_SECONDS, minimum=0)


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _json_dumps(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _sign(signing_input: bytes) -> str:
    digest = hmac.new(_get_token_secret(), signing_input, hashlib.sha256).digest()
    return _base64url_encode(digest)


def extract_bearer_token(header_value: Optional[str]) -> Optional[str]:
    if not header_value:
        return None

    parts = header_value.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    token = parts[1].strip()
    return token or None


def extract_request_auth_token(request) -> Optional[str]:
    return (
        extract_bearer_token(request.META.get("HTTP_AUTHORIZATION"))
        or str(request.COOKIES.get(AUTH_COOKIE_NAME) or "").strip()
        or None
    )


def _auth_cookie_secure() -> bool:
    raw_value = os.getenv("AUTH_COOKIE_SECURE", "").strip().lower()
    if raw_value:
        return raw_value in {"1", "true", "yes", "y", "on"}
    return not settings.DEBUG


def set_auth_cookie(response, token_payload: Dict[str, Any]) -> None:
    token = str(token_payload.get("token") or "").strip()
    if not token:
        return
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=max(int(token_payload.get("tokenExpiresIn") or 0), 1),
        httponly=True,
        secure=_auth_cookie_secure(),
        samesite=os.getenv("AUTH_COOKIE_SAMESITE", "Lax") or "Lax",
        path="/",
    )


def delete_auth_cookie(response) -> None:
    response.delete_cookie(
        AUTH_COOKIE_NAME,
        path="/",
        samesite=os.getenv("AUTH_COOKIE_SAMESITE", "Lax") or "Lax",
    )


def public_token_metadata(token_payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in token_payload.items()
        if key != "token"
    }


def issue_auth_token(
    user_id: str,
    auth_version: int = 1,
    *,
    session_id: str | uuid.UUID,
    actor_user_id: Optional[str] = None,
    actor_auth_version: Optional[int] = None,
    avatar_url: Optional[str] = None,
    display_name: Optional[str] = None,
    session_started_at: Optional[int] = None,
    auth_channel: str = AUTH_CHANNEL_DINGTALK,
    audience: str = AUDIENCE_PLATFORM,
) -> Dict[str, Any]:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        raise AuthTokenError("Cannot issue auth token without userId")
    try:
        normalized_session_id = str(uuid.UUID(str(session_id)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise AuthTokenError("Cannot issue auth token without a valid sessionId") from exc
    normalized_auth_channel = str(auth_channel or "").strip()
    normalized_audience = str(audience or "").strip()
    if (normalized_auth_channel, normalized_audience) not in VALID_CHANNEL_AUDIENCES:
        raise AuthTokenError("Cannot issue auth token for an invalid channel or audience")

    issued_at = int(time.time())
    session_started = int(session_started_at or issued_at)
    if session_started > issued_at:
        session_started = issued_at
    absolute_expires_at = session_started + _get_session_max_age_seconds()
    if issued_at >= absolute_expires_at:
        raise AuthTokenError("登录会话已达到最大有效期，请重新登录")

    expires_at = min(issued_at + _get_token_ttl_seconds(), absolute_expires_at)
    payload = {
        "sub": normalized_user_id,
        "sid": normalized_session_id,
        "av": max(int(auth_version or 1), 1),
        "sai": session_started,
        "jti": uuid.uuid4().hex,
        "iat": issued_at,
        "exp": expires_at,
        "chn": normalized_auth_channel,
        "aud": normalized_audience,
    }
    normalized_actor_user_id = str(actor_user_id or "").strip()
    if normalized_actor_user_id and normalized_actor_user_id != normalized_user_id:
        payload["act"] = normalized_actor_user_id
        payload["aav"] = max(int(actor_auth_version or 1), 1)
    normalized_avatar_url = str(avatar_url or "").strip()
    if normalized_avatar_url:
        payload["au"] = normalized_avatar_url
    normalized_display_name = str(display_name or "").strip()
    if normalized_display_name:
        payload["dn"] = normalized_display_name[:120]
    header = {
        "alg": "HS256",
        "typ": "JWT",
    }

    encoded_header = _base64url_encode(_json_dumps(header))
    encoded_payload = _base64url_encode(_json_dumps(payload))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    encoded_signature = _sign(signing_input)
    token = f"{encoded_header}.{encoded_payload}.{encoded_signature}"

    return {
        "token": token,
        "sessionId": normalized_session_id,
        "tokenType": "Bearer",
        "tokenExpiresAt": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        "tokenExpiresIn": expires_at - issued_at,
        "sessionExpiresAt": datetime.fromtimestamp(absolute_expires_at, tz=timezone.utc).isoformat(),
        "sessionExpiresIn": max(absolute_expires_at - issued_at, 0),
    }


def decode_auth_token(token: str) -> Dict[str, Any]:
    normalized_token = str(token or "").strip()
    if not normalized_token:
        raise AuthTokenError("缺少登录令牌")
    if len(normalized_token) > MAX_TOKEN_LENGTH:
        raise AuthTokenError("登录令牌过长")

    parts = normalized_token.split(".")
    if len(parts) != 3:
        raise AuthTokenError("登录令牌格式无效")

    encoded_header, encoded_payload, encoded_signature = parts
    try:
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    except UnicodeEncodeError as exc:
        raise AuthTokenError("登录令牌格式无效") from exc
    expected_signature = _sign(signing_input)
    if not hmac.compare_digest(encoded_signature, expected_signature):
        raise AuthTokenError("登录令牌签名无效")

    try:
        header = json.loads(_base64url_decode(encoded_header).decode("utf-8"))
        payload = json.loads(_base64url_decode(encoded_payload).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error) as exc:
        raise AuthTokenError("登录令牌内容无效") from exc

    if header.get("alg") != "HS256":
        raise AuthTokenError("登录令牌算法无效")
    if header.get("typ") != "JWT":
        raise AuthTokenError("登录令牌类型无效")

    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        raise AuthTokenError("登录令牌缺少用户标识")
    token_id = str(payload.get("jti") or "").strip()
    if not token_id:
        raise AuthTokenError("登录令牌字段无效")
    try:
        session_id = str(uuid.UUID(str(payload.get("sid") or "")))
    except (TypeError, ValueError, AttributeError) as exc:
        raise AuthTokenError("登录令牌会话标识无效") from exc

    try:
        auth_version = int(payload.get("av", 1))
        issued_at = int(payload["iat"])
        session_started = int(payload["sai"])
        expires_at = int(payload["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthTokenError("登录令牌字段无效") from exc

    if auth_version < 1:
        raise AuthTokenError("登录令牌版本无效")
    if session_started < 1 or issued_at < session_started:
        raise AuthTokenError("登录令牌会话字段无效")
    if expires_at <= issued_at:
        raise AuthTokenError("登录令牌过期时间无效")

    auth_channel = str(payload.get("chn") or AUTH_CHANNEL_DINGTALK).strip()
    audience = str(payload.get("aud") or AUDIENCE_PLATFORM).strip()
    if (auth_channel, audience) not in VALID_CHANNEL_AUDIENCES:
        raise AuthTokenError("登录令牌渠道无效")

    actor_user_id = str(payload.get("act") or "").strip()
    if actor_user_id:
        try:
            actor_auth_version = int(payload.get("aav", 1))
        except (TypeError, ValueError) as exc:
            raise AuthTokenError("登录令牌代理字段无效") from exc
        if actor_auth_version < 1:
            raise AuthTokenError("登录令牌代理版本无效")
        payload["act"] = actor_user_id
        payload["aav"] = actor_auth_version

    avatar_url = str(payload.get("au") or "").strip()
    if avatar_url:
        payload["au"] = avatar_url
    display_name = str(payload.get("dn") or "").strip()
    if display_name:
        payload["dn"] = display_name[:120]

    now = int(time.time())
    leeway = _get_token_clock_leeway_seconds()
    if issued_at > now + leeway:
        raise AuthTokenError("登录令牌签发时间无效")
    if now >= expires_at + leeway:
        raise AuthTokenError("登录已过期，请重新登录")
    if now >= session_started + _get_session_max_age_seconds():
        raise AuthTokenError("登录会话已达到最大有效期，请重新登录")

    payload["sub"] = user_id
    payload["sid"] = session_id
    payload["av"] = auth_version
    payload["jti"] = token_id
    payload["iat"] = issued_at
    payload["sai"] = session_started
    payload["exp"] = expires_at
    payload["chn"] = auth_channel
    payload["aud"] = audience
    return payload
