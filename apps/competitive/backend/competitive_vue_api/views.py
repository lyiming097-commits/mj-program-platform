from django.db import connection
from django.http import JsonResponse


def health(_request):
    return JsonResponse({"ok": True})


def health_live(_request):
    return JsonResponse({"ok": True})


def health_ready(_request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({
            "ok": False,
            "code": "DATABASE_UNAVAILABLE",
            "database": "unavailable",
        }, status=503)
    return JsonResponse({"ok": True, "database": "ok"})


def session(request):
    return JsonResponse({
        "ok": True,
        "userId": request.auth_user_id,
        "name": request.auth_user_name,
        "actorUserId": request.auth_actor_user_id,
        "actorName": request.auth_actor_name,
        "isProxying": request.auth_is_proxy,
        "canUseSystemAdmin": request.auth_can_use_system_admin,
    })
