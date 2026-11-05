from django.http import JsonResponse

from .session import AuthSessionError, bind_auth_session_to_request, refresh_auth_token, validate_auth_token
from .tokens import AuthTokenError
from .tokens import AUTH_COOKIE_NAME, extract_request_auth_token, set_auth_cookie


class AuthTokenMiddleware:
    REFRESH_PATHS = {
        "/api/auth/session/validate",
    }
    PUBLIC_PATHS = {
        "/api/health",
        "/api/health/",
        "/api/health/live",
        "/api/health/ready",
        "/api/auth/code",
        "/api/auth/dev/login",
        "/api/auth/wechat-mini/login",
        "/api/auth/wechat-mini/register",
        "/api/auth/wechat-mini/dev-login",
        "/api/dingtalk/check_env",
        "/api/dingtalk/jsapi_config",
    }
    PUBLIC_PREFIXES = (
        "/api/org/robot-messages/public-images/",
        "/api/internal/",
    )
    WECHAT_MINI_PATHS = {
        "/api/auth/logout",
        "/api/auth/wechat-mini/refresh",
        "/api/auth/wechat-mini/account",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS" or not request.path.startswith("/api/"):
            return self.get_response(request)

        if request.path in self.PUBLIC_PATHS or any(request.path.startswith(prefix) for prefix in self.PUBLIC_PREFIXES):
            return self.get_response(request)

        token = extract_request_auth_token(request)
        if not token:
            return JsonResponse(
                {
                    "ok": False,
                    "code": "MISSING_AUTH_TOKEN",
                    "error": "Missing auth token",
                },
                status=401,
            )

        try:
            session = validate_auth_token(token)
        except AuthSessionError as exc:
            response = JsonResponse(
                {
                    "ok": False,
                    "code": exc.code,
                    "error": str(exc),
                },
                status=exc.status_code,
            )
            return response

        if session.claims.get("chn") == "wechat-mini" and request.path not in self.WECHAT_MINI_PATHS:
            return JsonResponse(
                {
                    "ok": False,
                    "code": "AUTH_CHANNEL_FORBIDDEN",
                    "error": "微信小程序账号不能访问管理端接口",
                },
                status=403,
            )

        bind_auth_session_to_request(request, session)
        response = self.get_response(request)
        if (
            request.path in self.REFRESH_PATHS
            and getattr(response, "status_code", 500) < 400
            and AUTH_COOKIE_NAME not in response.cookies
        ):
            try:
                token_payload = refresh_auth_token(session)
            except AuthTokenError:
                token_payload = None
            if token_payload is not None:
                set_auth_cookie(response, token_payload)
                response["X-Auth-Token-Expires-At"] = token_payload["tokenExpiresAt"]
                response["X-Auth-Token-Expires-In"] = str(token_payload["tokenExpiresIn"])
        return response
