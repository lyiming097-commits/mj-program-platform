from pathlib import Path
import sys


try:
    from platform_auth.client import AuthIntrospectionError, introspect_auth_token as _introspect_auth_token
    from platform_auth.middleware import authentication_error_response, validate_introspection_identity
except ModuleNotFoundError as exc:
    if exc.name != "platform_auth":
        raise
    shared_package = Path(__file__).resolve().parents[5] / "packages" / "platform-backend"
    sys.path.insert(0, str(shared_package))
    from platform_auth.client import AuthIntrospectionError, introspect_auth_token as _introspect_auth_token
    from platform_auth.middleware import authentication_error_response, validate_introspection_identity


def introspect_auth_token(token: str, *, request_id: str = ""):
    return _introspect_auth_token(
        token,
        request_id=request_id,
        default_service_name="cable-mall-backend",
    )


__all__ = [
    "AuthIntrospectionError",
    "authentication_error_response",
    "introspect_auth_token",
    "validate_introspection_identity",
]
