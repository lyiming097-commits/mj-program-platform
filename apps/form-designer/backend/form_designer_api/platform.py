from pathlib import Path
import sys


try:
    from platform_auth.middleware import AuthTokenMiddleware as PlatformAuthTokenMiddleware
    from platform_auth.security import SameOriginWriteMiddleware as PlatformSameOriginWriteMiddleware
except ModuleNotFoundError as exc:
    if exc.name != "platform_auth":
        raise
    for parent in Path(__file__).resolve().parents:
        shared_package = parent / "packages" / "platform-backend"
        if shared_package.is_dir():
            sys.path.insert(0, str(shared_package))
            break
    else:
        raise
    from platform_auth.middleware import AuthTokenMiddleware as PlatformAuthTokenMiddleware
    from platform_auth.security import SameOriginWriteMiddleware as PlatformSameOriginWriteMiddleware


class SameOriginWriteMiddleware(PlatformSameOriginWriteMiddleware):
    # TLS terminates before the platform gateway. Accept only public origins
    # already listed in CSRF_TRUSTED_ORIGINS when the app sees the HTTP hop.
    allow_trusted_origins = True


class AuthTokenMiddleware(PlatformAuthTokenMiddleware):
    default_service_name = "form-designer-backend"
    public_paths = PlatformAuthTokenMiddleware.public_paths | {
        "/api/form-designer/health/",
        "/api/form-designer/health/live",
        "/api/form-designer/health/ready",
    }
