from __future__ import annotations

import hashlib
import ipaddress
import time

from django.core.cache import cache
from django.http import JsonResponse


def _client_ip(request) -> str:
    forwarded_for = str(request.META.get("HTTP_X_FORWARDED_FOR") or "")
    candidates = [item.strip() for item in forwarded_for.split(",") if item.strip()]
    candidates.extend(
        [
            str(request.META.get("HTTP_X_REAL_IP") or "").strip(),
            str(request.META.get("REMOTE_ADDR") or "").strip(),
        ]
    )
    for candidate in candidates:
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return "unknown"


def enforce_rate_limit(request, *, scope: str, limit: int, window_seconds: int) -> JsonResponse | None:
    window = max(int(window_seconds), 1)
    bucket = int(time.time()) // window
    identity = hashlib.sha256(_client_ip(request).encode("utf-8")).hexdigest()[:24]
    key = f"auth-rate:{scope}:{identity}:{bucket}"
    try:
        cache.add(key, 0, timeout=window + 5)
        attempts = cache.incr(key)
    except Exception:
        return None
    if attempts <= max(int(limit), 1):
        return None

    retry_after = window - (int(time.time()) % window)
    response = JsonResponse(
        {
            "ok": False,
            "code": "RATE_LIMITED",
            "error": "请求过于频繁，请稍后重试",
            "retryAfter": retry_after,
        },
        status=429,
    )
    response["Retry-After"] = str(retry_after)
    return response
