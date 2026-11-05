import os
from urllib.parse import urlsplit

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .client import DingTalkAPIError, build_jsapi_config
from ..auth.rate_limit import enforce_rate_limit


@require_GET
def check_dingtalk_env(request):
    """
    检查当前请求是否来自钉钉客户端环境。
    """
    user_agent = request.META.get("HTTP_USER_AGENT", "").lower()
    is_dingtalk = "dingtalk" in user_agent

    return JsonResponse({
        "is_dingtalk": is_dingtalk,
        "user_agent": user_agent,
    })


@require_GET
def jsapi_config(request):
    rate_limit_response = enforce_rate_limit(request, scope="dingtalk-jsapi", limit=60, window_seconds=60)
    if rate_limit_response is not None:
        return rate_limit_response
    url = (request.GET.get("url") or "").strip()
    parsed_url = urlsplit(url)
    allowed_origins = set()
    for item in os.getenv("DINGTALK_JSAPI_ALLOWED_ORIGINS", "").split(","):
        parsed_item = urlsplit(item.strip())
        if parsed_item.scheme in {"http", "https"} and parsed_item.netloc:
            allowed_origins.add(f"{parsed_item.scheme}://{parsed_item.netloc}".lower())
    if not allowed_origins and settings.DEBUG:
        allowed_origins.add(f"{'https' if request.is_secure() else 'http'}://{request.get_host()}".lower())
    if not allowed_origins:
        return JsonResponse(
            {"code": "JSAPI_ALLOWED_ORIGINS_NOT_CONFIGURED", "error": "JSAPI allowed origins are not configured"},
            status=503,
        )
    requested_origin = f"{parsed_url.scheme}://{parsed_url.netloc}".lower() if parsed_url.scheme and parsed_url.netloc else ""
    if parsed_url.scheme not in {"http", "https"} or not requested_origin:
        return JsonResponse({"error": "Invalid JSAPI signature URL"}, status=400)
    if requested_origin not in allowed_origins:
        return JsonResponse({"error": "JSAPI signature URL origin is not allowed"}, status=403)
    raw_js_api_list = (request.GET.get("jsApiList") or "").strip()
    js_api_list = [item.strip() for item in raw_js_api_list.split(",") if item.strip()]
    try:
        config = build_jsapi_config(url, js_api_list)
    except DingTalkAPIError as exc:
        return JsonResponse(
            {"ok": False, "code": "DINGTALK_API_ERROR", "error": str(exc)},
            status=exc.status,
        )
    return JsonResponse(config)
