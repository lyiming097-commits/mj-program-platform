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
    # DingTalk can load the workbench on either the standard HTTPS origin or
    # the externally forwarded 4433 origin. Both are explicitly configured.
    allow_trusted_origins = True


class AuthTokenMiddleware(PlatformAuthTokenMiddleware):
    default_service_name = "after-sales-backend"
    public_paths = PlatformAuthTokenMiddleware.public_paths | {
        "/api/after-sales/health/",
        "/api/after-sales/health/live",
        "/api/after-sales/health/ready",
        "/api/after-sales/public/demo",
        "/api/after-sales/public/provider-tags",
    }
