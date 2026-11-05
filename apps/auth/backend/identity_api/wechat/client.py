from __future__ import annotations

import os

import requests


CODE_TO_SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WeChatMiniAPIError(Exception):
    def __init__(self, message: str, *, status: int = 502, code: str = "WECHAT_API_ERROR"):
        super().__init__(message)
        self.status = status
        self.code = code


def configured_app_id() -> str:
    return os.getenv("WECHAT_MINI_APP_ID", "").strip()


def _timeout_seconds() -> float:
    try:
        return min(max(float(os.getenv("WECHAT_MINI_API_TIMEOUT_SECONDS", "5") or "5"), 1.0), 15.0)
    except (TypeError, ValueError):
        return 5.0


def exchange_login_code(code: str) -> dict[str, str]:
    app_id = configured_app_id()
    app_secret = os.getenv("WECHAT_MINI_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise WeChatMiniAPIError(
            "微信小程序登录尚未配置",
            status=503,
            code="WECHAT_MINI_NOT_CONFIGURED",
        )

    normalized_code = str(code or "").strip()
    if not normalized_code:
        raise WeChatMiniAPIError("缺少微信登录凭证", status=400, code="WECHAT_LOGIN_CODE_REQUIRED")

    try:
        response = requests.get(
            CODE_TO_SESSION_URL,
            params={
                "appid": app_id,
                "secret": app_secret,
                "js_code": normalized_code,
                "grant_type": "authorization_code",
            },
            timeout=_timeout_seconds(),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeChatMiniAPIError("微信登录服务暂时不可用") from exc

    if not isinstance(payload, dict):
        raise WeChatMiniAPIError("微信登录服务返回异常")
    if payload.get("errcode") not in (None, 0, "0"):
        errcode = str(payload.get("errcode") or "")
        if errcode in {"40029", "40163"}:
            raise WeChatMiniAPIError("微信登录凭证无效或已使用", status=401, code="WECHAT_LOGIN_CODE_INVALID")
        raise WeChatMiniAPIError("微信登录服务拒绝了本次请求")

    openid = str(payload.get("openid") or "").strip()
    if not openid:
        raise WeChatMiniAPIError("微信登录服务未返回用户标识")
    return {
        "app_id": app_id,
        "openid": openid,
        "unionid": str(payload.get("unionid") or "").strip(),
    }
