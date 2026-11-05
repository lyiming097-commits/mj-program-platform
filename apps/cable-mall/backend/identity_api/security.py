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
    pass
