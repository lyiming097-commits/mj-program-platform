import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password


EXTERNAL_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60


class ExternalAuthError(Exception):
    pass


def hash_external_password(raw_password: str) -> str:
    return make_password(str(raw_password or ""))


def verify_external_password(raw_password: str, encoded_password: str) -> bool:
    return check_password(str(raw_password or ""), str(encoded_password or ""))


def generate_external_password(length: int = 10) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(max(length, 8)))


def external_password_version(value) -> int:
    if not value:
        return 0
    return int(value.timestamp() * 1_000_000)


def _secret() -> bytes:
    return f"cable-mall-external:{settings.SECRET_KEY}".encode("utf-8")


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(f"{value}{'=' * (-len(value) % 4)}".encode("ascii"))


def _sign(signing_input: bytes) -> str:
    digest = hmac.new(_secret(), signing_input, hashlib.sha256).digest()
    return _b64_encode(digest)


def issue_external_token(account) -> dict:
    issued_at = int(time.time())
    expires_at = issued_at + EXTERNAL_TOKEN_TTL_SECONDS
    password_changed_at = getattr(account, "password_changed_at", None) or getattr(account, "updated_at", None)
    password_version = external_password_version(password_changed_at) or issued_at
    payload = {
        "typ": "cable_mall_external",
        "sub": account.id,
        "username": account.username,
        "owner": account.owner_user_id,
        "pwd": password_version,
        "iat": issued_at,
        "exp": expires_at,
    }
    encoded_payload = _b64_encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    signature = _sign(encoded_payload.encode("ascii"))
    token = f"{encoded_payload}.{signature}"
    return {
        "token": token,
        "tokenType": "Bearer",
        "tokenExpiresAt": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        "tokenExpiresIn": EXTERNAL_TOKEN_TTL_SECONDS,
    }


def decode_external_token(token: str) -> dict:
    normalized = str(token or "").strip()
    parts = normalized.split(".")
    if len(parts) != 2:
        raise ExternalAuthError("外部登录令牌格式无效")
    encoded_payload, signature = parts
    expected = _sign(encoded_payload.encode("ascii"))
    if not hmac.compare_digest(signature, expected):
        raise ExternalAuthError("外部登录令牌签名无效")
    try:
        payload = json.loads(_b64_decode(encoded_payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalAuthError("外部登录令牌内容无效") from exc
    if payload.get("typ") != "cable_mall_external":
        raise ExternalAuthError("外部登录令牌类型无效")
    try:
        expires_at = int(payload["exp"])
        account_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalAuthError("外部登录令牌字段无效") from exc
    if int(time.time()) >= expires_at:
        raise ExternalAuthError("外部登录已过期，请重新登录")
    payload["sub"] = account_id
    payload["exp"] = expires_at
    try:
        payload["pwd"] = int(payload.get("pwd") or 0)
    except (TypeError, ValueError):
        payload["pwd"] = 0
    return payload
