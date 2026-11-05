from __future__ import annotations

import os
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from redis import Redis

from .tasks import SYNC_SCHEDULER_HEARTBEAT_KEY, SYNC_WORKER_HEARTBEAT_KEY


@require_GET
def health_live(_request):
    return JsonResponse({"ok": True, "service": "auth-backend", "status": "live"})


@require_GET
def health_ready(_request):
    checks: dict[str, bool] = {
        "database": False,
        "cache": False,
        "taskBroker": False,
        "syncWorker": False,
        "syncScheduler": False,
        "dingtalkConfig": bool(
            settings.DEBUG
            or (
                os.getenv("DINGTALK_CLIENT_ID", "").strip()
                and os.getenv("DINGTALK_CLIENT_SECRET", "").strip()
                and os.getenv("DINGTALK_CORP_ID", "").strip()
            )
        ),
    }

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            checks["database"] = cursor.fetchone() == (1,)
    except Exception:
        checks["database"] = False

    cache_key = f"auth-health:{uuid.uuid4().hex}"
    try:
        cache.set(cache_key, "ready", timeout=10)
        checks["cache"] = cache.get(cache_key) == "ready"
        cache.delete(cache_key)
        if checks["cache"]:
            checks["syncWorker"] = bool(cache.get(SYNC_WORKER_HEARTBEAT_KEY))
            checks["syncScheduler"] = bool(cache.get(SYNC_SCHEDULER_HEARTBEAT_KEY))
    except Exception:
        checks["cache"] = False

    try:
        broker = Redis.from_url(os.getenv("AUTH_CELERY_BROKER_URL", "redis://redis:6379/1"))
        checks["taskBroker"] = bool(broker.ping())
        broker.close()
    except Exception:
        checks["taskBroker"] = False

    ready = all(checks.values())
    return JsonResponse(
        {
            "ok": ready,
            "service": "auth-backend",
            "status": "ready" if ready else "not_ready",
            "checks": checks,
        },
        status=200 if ready else 503,
    )
