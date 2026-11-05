from pathlib import Path
import sys


try:
    from platform_auth.security import SameOriginWriteMiddleware as PlatformSameOriginWriteMiddleware
except ModuleNotFoundError as exc:
    if exc.name != "platform_auth":
        raise
    shared_package = Path(__file__).resolve().parents[4] / "packages" / "platform-backend"
    sys.path.insert(0, str(shared_package))
    from platform_auth.security import SameOriginWriteMiddleware as PlatformSameOriginWriteMiddleware


class SameOriginWriteMiddleware(PlatformSameOriginWriteMiddleware):
    excluded_prefixes = ("/api/internal/",)
    allow_trusted_origins = True

    _wechat_mini_public_write_paths = {
        "/api/auth/wechat-mini/login",
        "/api/auth/wechat-mini/register",
        "/api/auth/wechat-mini/dev-login",
    }

    def _is_protected(self, request) -> bool:
        # Native mini-program requests can carry a DevTools Origin but never use
        # the management cookie. These endpoints authenticate with a WeChat code
        # or a one-time registration token and enforce their own rate limits.
        if str(request.path or "") in self._wechat_mini_public_write_paths:
            return False
        return super()._is_protected(request)
