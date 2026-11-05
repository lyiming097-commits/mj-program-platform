from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from typing import Any

import requests


DING_APP_ACCESS_TOKEN_URL = "https://oapi.dingtalk.com/gettoken"
DING_APP_ACCESS_TOKEN_V1_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
DING_USER_ACCESS_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"
DING_USER_PROFILE_URL = "https://api.dingtalk.com/v1.0/contact/users/me"
DING_GET_USER_INFO_BY_CODE_URL = "https://oapi.dingtalk.com/topapi/v2/user/getuserinfo"
DING_GET_USER_DETAIL_BY_USERID_URL = "https://oapi.dingtalk.com/topapi/v2/user/get"
DING_GET_USERID_BY_UNIONID_URL = "https://oapi.dingtalk.com/topapi/user/getbyunionid"
DING_JSAPI_TICKET_URL = "https://oapi.dingtalk.com/get_jsapi_ticket"

_APP_ACCESS_TOKEN_CACHE: dict[str, Any] = {"token": "", "expires_at": 0}
_JSAPI_TICKET_CACHE: dict[str, Any] = {"ticket": "", "expires_at": 0}

_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)([\"']?(?:access[_-]?token|refresh[_-]?token|app[_-]?secret|client[_-]?secret|auth[_-]?code|jsapi[_-]?ticket)[\"']?\s*[:=]\s*[\"']?)([^&,\s}\"']+)"
)


def redact_dingtalk_text(value: Any) -> str:
    text = str(value or "")
    return _SENSITIVE_ASSIGNMENT_RE.sub(r"\1[REDACTED]", text)


def _is_sensitive_key(value: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    return normalized in {
        "accesstoken",
        "refreshtoken",
        "appsecret",
        "clientsecret",
        "authcode",
        "jsapiticket",
        "ticket",
    } or normalized.endswith("secret") or normalized.endswith("token")


def sanitize_dingtalk_detail(value: Any, *, depth: int = 0) -> Any:
    if depth >= 8:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(key) else sanitize_dingtalk_detail(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_dingtalk_detail(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        return redact_dingtalk_text(value)
    return value


class DingTalkAPIError(Exception):
    def __init__(self, message: str, *, detail: Any = None, status: int = 502):
        super().__init__(redact_dingtalk_text(message))
        self.detail = sanitize_dingtalk_detail(detail)
        self.status = status


def safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def get_client_config() -> tuple[str, str]:
    client_id = os.getenv("DINGTALK_CLIENT_ID", "").strip()
    client_secret = os.getenv("DINGTALK_CLIENT_SECRET", "").strip()
    return client_id, client_secret


def get_jsapi_app_config() -> tuple[str, str]:
    corp_id = os.getenv("DINGTALK_CORP_ID", "").strip()
    agent_id = os.getenv("DINGTALK_AGENT_ID", "").strip()
    return corp_id, agent_id


def _pick_first(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _format_api_error(default_message: str, payload: Any) -> str:
    if not isinstance(payload, dict):
        return default_message

    errcode = str(_pick_first(payload.get("errcode"), payload.get("code"), "") or "").strip()
    errmsg = str(_pick_first(payload.get("errmsg"), payload.get("message"), payload.get("error"), "") or "").strip()
    if errcode == "60020" or "白名单" in errmsg:
        return (
            "钉钉应用服务器出口 IP 不在白名单中。"
            f"{errmsg or '请在钉钉开放平台把当前服务器出口 IP 加入这个应用的服务器出口 IP 白名单。'}"
        )
    if errmsg:
        return f"{default_message}：{errmsg}"
    if errcode:
        return f"{default_message}：钉钉错误码 {errcode}"
    return default_message


def _require_client_config() -> tuple[str, str]:
    client_id, client_secret = get_client_config()
    if not client_id or not client_secret:
        raise DingTalkAPIError(
            "Server missing DINGTALK_CLIENT_ID or DINGTALK_CLIENT_SECRET",
            status=500,
        )
    return client_id, client_secret


def _request_json(method: str, url: str, **kwargs: Any) -> tuple[requests.Response, Any]:
    last_error: requests.RequestException | None = None
    timeout = kwargs.pop("timeout", 10)
    for attempt in range(3):
        try:
            response = requests.request(method, url, timeout=timeout, **kwargs)
            return response, safe_json(response)
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))

    error_type = type(last_error).__name__ if last_error is not None else "RequestException"
    raise DingTalkAPIError(
        "Failed to request DingTalk API",
        detail={"errorType": error_type},
    ) from None


def _get_user_access_token(auth_code: str) -> str:
    client_id, client_secret = _require_client_config()
    response, payload = _request_json(
        "POST",
        DING_USER_ACCESS_TOKEN_URL,
        json={
            "clientId": client_id,
            "clientSecret": client_secret,
            "code": auth_code,
            "grantType": "authorization_code",
        },
    )
    if response.status_code >= 400:
        raise DingTalkAPIError(
            _format_api_error("DingTalk user access token request failed", payload),
            detail=payload,
        )

    access_token = payload.get("accessToken") or payload.get("access_token")
    if not access_token:
        raise DingTalkAPIError(
            "No user access token in DingTalk response",
            detail=payload,
        )
    return access_token


def _get_app_access_token() -> str:
    now = int(time.time())
    cached_token = str(_APP_ACCESS_TOKEN_CACHE.get("token") or "")
    if cached_token and int(_APP_ACCESS_TOKEN_CACHE.get("expires_at") or 0) > now:
        return cached_token

    client_id, client_secret = _require_client_config()
    try:
        response, payload = _request_json(
            "GET",
            DING_APP_ACCESS_TOKEN_URL,
            params={
                "appkey": client_id,
                "appsecret": client_secret,
            },
        )
        errcode = payload.get("errcode") if isinstance(payload, dict) else None
        if response.status_code >= 400 or errcode not in (0, "0"):
            raise DingTalkAPIError(
                _format_api_error("DingTalk app access token request failed", payload),
                detail=payload,
            )
    except DingTalkAPIError as legacy_error:
        response, payload = _request_json(
            "POST",
            DING_APP_ACCESS_TOKEN_V1_URL,
            json={
                "appKey": client_id,
                "appSecret": client_secret,
            },
        )
        if response.status_code >= 400:
            raise DingTalkAPIError(
                _format_api_error("DingTalk app access token request failed", payload),
                detail={
                    "oapiGetToken": {
                        "error": str(legacy_error),
                        "detail": legacy_error.detail,
                    },
                    "v1AccessToken": payload,
                },
            ) from legacy_error

    access_token = payload.get("accessToken") or payload.get("access_token")
    if not access_token:
        raise DingTalkAPIError(
            "No app access token in DingTalk response",
            detail=payload,
        )
    expires_in = int(_pick_first(payload.get("expireIn"), payload.get("expiresIn"), payload.get("expires_in"), 7200) or 7200)
    _APP_ACCESS_TOKEN_CACHE["token"] = access_token
    _APP_ACCESS_TOKEN_CACHE["expires_at"] = now + max(60, expires_in - 120)
    return access_token


def _get_jsapi_ticket(app_access_token: str) -> str:
    now = int(time.time())
    cached_ticket = str(_JSAPI_TICKET_CACHE.get("ticket") or "")
    if cached_ticket and int(_JSAPI_TICKET_CACHE.get("expires_at") or 0) > now:
        return cached_ticket

    response, payload = _request_json(
        "GET",
        f"{DING_JSAPI_TICKET_URL}?access_token={app_access_token}",
    )
    errcode = payload.get("errcode") if isinstance(payload, dict) else None
    if response.status_code >= 400 or errcode not in (0, "0"):
        raise DingTalkAPIError(
            _format_api_error("DingTalk JSAPI ticket request failed", payload),
            detail=payload,
        )

    ticket = payload.get("ticket") if isinstance(payload, dict) else ""
    if not ticket:
        raise DingTalkAPIError(
            "No JSAPI ticket in DingTalk response",
            detail=payload,
        )
    expires_in = int(_pick_first(payload.get("expires_in"), payload.get("expireIn"), payload.get("expiresIn"), 7200) or 7200)
    _JSAPI_TICKET_CACHE["ticket"] = ticket
    _JSAPI_TICKET_CACHE["expires_at"] = now + max(60, expires_in - 120)
    return str(ticket)


def build_jsapi_config(url: str, js_api_list: list[str] | None = None) -> dict[str, Any]:
    normalized_url = str(url or "").split("#", 1)[0].strip()
    if not normalized_url:
        raise DingTalkAPIError("Missing JSAPI signature URL", status=400)

    app_access_token = _get_app_access_token()
    ticket = _get_jsapi_ticket(app_access_token)
    nonce_str = uuid.uuid4().hex
    timestamp = int(time.time())
    plain = f"jsapi_ticket={ticket}&noncestr={nonce_str}&timestamp={timestamp}&url={normalized_url}"
    signature = hashlib.sha1(plain.encode("utf-8")).hexdigest()
    corp_id, agent_id = get_jsapi_app_config()

    return {
        "corpId": corp_id,
        "agentId": agent_id,
        "timeStamp": timestamp,
        "nonceStr": nonce_str,
        "signature": signature,
        "url": normalized_url,
        "jsApiList": js_api_list or [],
    }


def _get_user_profile_by_user_access_token(access_token: str) -> dict[str, Any]:
    response, payload = _request_json(
        "GET",
        DING_USER_PROFILE_URL,
        headers={"x-acs-dingtalk-access-token": access_token},
    )
    if response.status_code >= 400:
        raise DingTalkAPIError(
            _format_api_error("DingTalk user info request failed", payload),
            detail=payload,
        )
    return payload if isinstance(payload, dict) else {"raw": payload}


def _get_user_identity_by_login_code(app_access_token: str, auth_code: str) -> dict[str, Any]:
    response, payload = _request_json(
        "POST",
        f"{DING_GET_USER_INFO_BY_CODE_URL}?access_token={app_access_token}",
        json={"code": auth_code},
    )
    errcode = payload.get("errcode") if isinstance(payload, dict) else None
    if response.status_code >= 400 or errcode not in (0, "0"):
        raise DingTalkAPIError(
            _format_api_error("DingTalk get user info by code request failed", payload),
            detail=payload,
        )

    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise DingTalkAPIError(
            "DingTalk get user info by code response is missing result",
            detail=payload,
        )
    return result


def _get_user_detail_by_userid(app_access_token: str, userid: str) -> dict[str, Any]:
    response, payload = _request_json(
        "POST",
        f"{DING_GET_USER_DETAIL_BY_USERID_URL}?access_token={app_access_token}",
        json={
            "userid": userid,
            "language": "zh_CN",
        },
    )
    errcode = payload.get("errcode") if isinstance(payload, dict) else None
    if response.status_code >= 400 or errcode not in (0, "0"):
        raise DingTalkAPIError(
            _format_api_error("DingTalk user detail request failed", payload),
            detail=payload,
        )

    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise DingTalkAPIError(
            "DingTalk user detail response is missing result",
            detail=payload,
        )
    return result


def _get_userid_by_unionid(app_access_token: str, unionid: str) -> str:
    response, payload = _request_json(
        "POST",
        f"{DING_GET_USERID_BY_UNIONID_URL}?access_token={app_access_token}",
        json={"unionid": unionid},
    )
    errcode = payload.get("errcode") if isinstance(payload, dict) else None
    if response.status_code >= 400 or errcode not in (0, "0"):
        raise DingTalkAPIError(
            _format_api_error("DingTalk get userid by unionid request failed", payload),
            detail=payload,
        )

    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise DingTalkAPIError(
            "DingTalk get userid by unionid response is missing result",
            detail=payload,
        )

    userid = _pick_first(result.get("userid"), result.get("userId"))
    if not userid:
        raise DingTalkAPIError(
            "DingTalk get userid by unionid response is missing userid",
            detail=payload,
        )
    return str(userid)


def _normalize_user_payload(
    primary_payload: dict[str, Any],
    *,
    login_type: str,
    reason: str,
    raw: Any,
    access_token: str,
    access_token_type: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra = extra or {}

    raw_profile = raw.get("profile", {}) if isinstance(raw, dict) else {}
    raw_detail = raw.get("detail", {}) if isinstance(raw, dict) else {}

    avatar_url = _pick_first(
        primary_payload.get("avatarUrl"),
        primary_payload.get("avatar"),
        primary_payload.get("avatar_url"),
        extra.get("avatarUrl"),
        extra.get("avatar"),
        extra.get("avatar_url"),
        raw_profile.get("avatarUrl") if isinstance(raw_profile, dict) else None,
        raw_profile.get("avatar") if isinstance(raw_profile, dict) else None,
        raw_profile.get("avatar_url") if isinstance(raw_profile, dict) else None,
        raw_detail.get("avatarUrl") if isinstance(raw_detail, dict) else None,
        raw_detail.get("avatar") if isinstance(raw_detail, dict) else None,
        raw_detail.get("avatar_url") if isinstance(raw_detail, dict) else None,
    )

    result = {
        "loginType": login_type,
        "reason": reason,
        "userId": _pick_first(
            primary_payload.get("userid"),
            primary_payload.get("userId"),
            extra.get("userid"),
            extra.get("userId"),
        ),
        "unionId": _pick_first(
            primary_payload.get("unionId"),
            primary_payload.get("union_id"),
            primary_payload.get("unionid"),
            extra.get("unionId"),
            extra.get("union_id"),
            extra.get("unionid"),
        ),
        "phone": _pick_first(
            primary_payload.get("mobile"),
            primary_payload.get("phoneNumber"),
            primary_payload.get("phone"),
            extra.get("mobile"),
            extra.get("phoneNumber"),
            extra.get("phone"),
        ),
        "nick": _pick_first(
            primary_payload.get("nick"),
            primary_payload.get("name"),
            extra.get("nick"),
            extra.get("name"),
        ),
        "stateCode": _pick_first(
            primary_payload.get("stateCode"),
            primary_payload.get("state_code"),
            extra.get("stateCode"),
            extra.get("state_code"),
        ),
        "avatarUrl": avatar_url or "",
    }

    optional_fields = {
        "name": _pick_first(primary_payload.get("name"), extra.get("name")),
        "deviceId": _pick_first(
            primary_payload.get("deviceId"),
            primary_payload.get("device_id"),
            extra.get("deviceId"),
            extra.get("device_id"),
        ),
        "sys": _pick_first(primary_payload.get("sys"), extra.get("sys")),
        "sysLevel": _pick_first(
            primary_payload.get("sysLevel"),
            primary_payload.get("sys_level"),
            extra.get("sysLevel"),
            extra.get("sys_level"),
        ),
        "associatedUnionId": _pick_first(
            primary_payload.get("associatedUnionId"),
            primary_payload.get("associated_unionid"),
            primary_payload.get("associatedUnionid"),
            extra.get("associatedUnionId"),
            extra.get("associated_unionid"),
            extra.get("associatedUnionid"),
        ),
        "openId": _pick_first(
            primary_payload.get("openId"),
            primary_payload.get("open_id"),
            extra.get("openId"),
            extra.get("open_id"),
        ),
    }

    for key, value in optional_fields.items():
        if value not in (None, ""):
            result[key] = value

    return result


def _login_with_oauth_user_code(
    auth_code: str,
    *,
    login_type: str,
    reason: str,
    raw_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    access_token = _get_user_access_token(auth_code)
    user_payload = _get_user_profile_by_user_access_token(access_token)
    userid = _pick_first(user_payload.get("userid"), user_payload.get("userId"))
    unionid = _pick_first(
        user_payload.get("unionId"),
        user_payload.get("union_id"),
        user_payload.get("unionid"),
    )
    app_access_token = ""
    detail_payload: dict[str, Any] = {}
    userid_lookup_error: dict[str, Any] | None = None
    detail_error: dict[str, Any] | None = None

    if not userid and unionid:
        try:
            app_access_token = _get_app_access_token()
            userid = _get_userid_by_unionid(app_access_token, str(unionid))
        except DingTalkAPIError as exc:
            userid_lookup_error = {
                "error": str(exc),
                "detail": exc.detail,
            }

    if userid:
        try:
            if not app_access_token:
                app_access_token = _get_app_access_token()
            detail_payload = _get_user_detail_by_userid(app_access_token, str(userid))
        except DingTalkAPIError as exc:
            detail_error = {
                "error": str(exc),
                "detail": exc.detail,
            }

    primary_payload = detail_payload or user_payload
    result = _normalize_user_payload(
        primary_payload,
        login_type=login_type,
        reason=reason,
        raw={
            "profile": user_payload,
            "detail": detail_payload,
            "useridLookupError": userid_lookup_error,
            "detailError": detail_error,
            **(raw_extra or {}),
        },
        access_token=access_token,
        access_token_type="user",
        extra={
            **user_payload,
            **({"userid": str(userid)} if userid else {}),
        },
    )
    if userid_lookup_error is not None:
        result["detailWarning"] = "DingTalk userid lookup by unionid request failed"
        result["reason"] = f"{reason}, but userid lookup request failed"
    elif detail_error is not None:
        result["detailWarning"] = "DingTalk user detail request failed"
        result["reason"] = f"{reason}, but user detail request failed"
    return result


def login_with_scan_code(auth_code: str) -> dict[str, Any]:
    return _login_with_oauth_user_code(
        auth_code,
        login_type="scan",
        reason="scan login succeeded",
    )


def login_with_workbench_code(auth_code: str) -> dict[str, Any]:
    try:
        app_access_token = _get_app_access_token()
        identity_payload = _get_user_identity_by_login_code(app_access_token, auth_code)
    except DingTalkAPIError as identity_error:
        try:
            result = _login_with_oauth_user_code(
                auth_code,
                login_type="workbench",
                reason="workbench oauth fallback login succeeded",
                raw_extra={
                    "workbenchIdentityError": {
                        "error": str(identity_error),
                        "detail": identity_error.detail,
                    },
                },
            )
        except DingTalkAPIError as oauth_error:
            raise DingTalkAPIError(
                f"{identity_error}；OAuth 兜底也失败：{oauth_error}",
                detail={
                    "workbenchIdentity": {
                        "error": str(identity_error),
                        "detail": identity_error.detail,
                    },
                    "oauthUserProfile": {
                        "error": str(oauth_error),
                        "detail": oauth_error.detail,
                    },
                },
                status=oauth_error.status,
            ) from oauth_error
        result["workbenchCodeWarning"] = (
            "DingTalk get user info by workbench code failed; "
            "used OAuth user profile fallback"
        )
        return result

    userid = _pick_first(identity_payload.get("userid"), identity_payload.get("userId"))
    detail_payload: dict[str, Any] = {}
    detail_error: dict[str, Any] | None = None
    if userid:
        try:
            detail_payload = _get_user_detail_by_userid(app_access_token, str(userid))
        except DingTalkAPIError as exc:
            detail_error = {
                "error": str(exc),
                "detail": exc.detail,
            }

    primary_payload = detail_payload or identity_payload
    result = _normalize_user_payload(
        primary_payload,
        login_type="workbench",
        reason="workbench login succeeded",
        raw={
            "identity": identity_payload,
            "detail": detail_payload,
            "detailError": detail_error,
        },
        access_token=app_access_token,
        access_token_type="app",
        extra=identity_payload,
    )
    if detail_error is not None:
        result["detailWarning"] = "DingTalk user detail request failed"
        result["reason"] = "workbench login succeeded, but user detail request failed"
    return result
