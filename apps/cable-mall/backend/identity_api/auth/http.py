from pathlib import Path
import sys


try:
    from platform_auth.client import AUTH_COOKIE_NAME, extract_bearer_token, extract_request_auth_token
except ModuleNotFoundError as exc:
    if exc.name != "platform_auth":
        raise
    shared_package = Path(__file__).resolve().parents[5] / "packages" / "platform-backend"
    sys.path.insert(0, str(shared_package))
    from platform_auth.client import AUTH_COOKIE_NAME, extract_bearer_token, extract_request_auth_token


__all__ = ["AUTH_COOKIE_NAME", "extract_bearer_token", "extract_request_auth_token"]
