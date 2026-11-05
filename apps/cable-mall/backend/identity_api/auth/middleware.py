from .http import extract_request_auth_token
from .introspection import (
    AuthIntrospectionError,
    authentication_error_response,
    introspect_auth_token,
    validate_introspection_identity,
)
from ..models import Employee


class AuthTokenMiddleware:
    PUBLIC_PATHS = {
        "/api/health",
        "/api/health/",
        "/api/auth/code",
        "/api/dingtalk/check_env",
        "/api/dingtalk/get_user_info_by_code",
        "/api/dingtalk/jsapi_config",
    }
    PUBLIC_PREFIXES = (
        "/api/external-cable-mall/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS" or not request.path.startswith("/api/"):
            return self.get_response(request)

        if request.path in self.PUBLIC_PATHS or any(request.path.startswith(prefix) for prefix in self.PUBLIC_PREFIXES):
            return self.get_response(request)

        token = extract_request_auth_token(request)
        if not token:
            return authentication_error_response(
                "Missing auth token",
                401,
                code="MISSING_AUTH_TOKEN",
            )

        request_id = str(request.headers.get("X-Request-Id") or "")
        try:
            introspection = introspect_auth_token(token, request_id=request_id)
            claims, user_id, actor_user_id = validate_introspection_identity(introspection)
        except AuthIntrospectionError as exc:
            return authentication_error_response(
                str(exc),
                exc.status_code,
                code=exc.code or "AUTH_INTROSPECTION_FAILED",
                request_id=exc.request_id or request_id,
            )

        employee = Employee.objects.filter(user_id=user_id).only(
            "user_id",
            "status",
            "account_status",
            "auth_version",
        ).first()
        actor_employee = employee if actor_user_id == user_id else Employee.objects.filter(user_id=actor_user_id).only(
            "user_id",
            "status",
            "account_status",
            "auth_version",
        ).first()
        is_proxying = bool(introspection.get("isProxying") is True or actor_user_id != user_id)
        can_use_system_admin = introspection.get("canUseSystemAdmin") is True

        request.auth_user_id = user_id
        request.auth_user_name = str(introspection.get("name") or introspection.get("nick") or "").strip()
        request.auth_employee = employee
        request.auth_actor_user_id = actor_user_id
        request.auth_actor_name = str(introspection.get("actorName") or introspection.get("actorDisplay") or "").strip()
        request.auth_actor_employee = actor_employee
        request.auth_is_proxy = is_proxying
        request.auth_is_system_admin = can_use_system_admin
        request.auth_can_use_system_admin = can_use_system_admin
        request.auth_token_claims = claims
        request.auth_introspection = introspection

        return self.get_response(request)
