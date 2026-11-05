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
    # HTTPS terminates at the platform gateway. Trust the explicitly configured
    # public origins so the browser's external port is accepted after proxying.
    allow_trusted_origins = True


class AuthTokenMiddleware(PlatformAuthTokenMiddleware):
    default_service_name = "competitive-backend"
    public_paths = PlatformAuthTokenMiddleware.public_paths | {
        "/api/competitive/health/",
        "/api/competitive/health/live",
        "/api/competitive/health/ready",
    }
