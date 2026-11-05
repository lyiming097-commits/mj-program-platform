import os
from datetime import date, timedelta

from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .domain import sync_expiry_statuses
from .models import Competitor, SettingItem, Submission, SubmissionStatus
from .product_catalog import ProductCatalogError, get_products
from .serializers import serialize_settings
from .setting_defaults import ensure_default_setting_items
from .view_helpers import error_response, request_access, submission_owner_filter


@require_http_methods(["GET"])
def map_config(request):
    _access, error = request_access(request)
    if error:
        return error
    key = os.getenv("AMAP_JS_KEY", "").strip()
    security_code = os.getenv("AMAP_SECURITY_KEY", "").strip()
    if not key or not security_code:
        return error_response("高德地图选点服务未配置", 503)
    return JsonResponse({"key": key, "securityCode": security_code})


@require_http_methods(["GET"])
def bootstrap(request):
    access, error = request_access(request)
    if error:
        return error
    sync_expiry_statuses()
    ensure_default_setting_items()
    settings = SettingItem.objects.order_by("group", "position", "label")
    return JsonResponse(
        {
            # Lists are intentionally kept as empty compatibility fields. Pages load
            # them through their paginated endpoints instead of blocking bootstrap on
            # every competitor and submission row.
            "products": [],
            "competitors": [],
            "submissions": [],
            "settings": serialize_settings(settings),
        }
    )


@require_http_methods(["GET"])
def expiry_summary(request):
    _access, error = request_access(request, "can_review")
    if error:
        return error
    try:
        days = int(request.GET.get("days", "30"))
    except ValueError:
        return error_response("days 参数无效", 422)
    if days < 1 or days > 90:
        return error_response("days 参数无效", 422)
    today = date.today()
    sync_expiry_statuses(today)
    rows = Submission.objects.filter(
        deleted_at__isnull=True,
        expires_on__lte=today + timedelta(days=days),
    ).order_by("expires_on", "id")
    try:
        products = {product["id"]: product for product in get_products()}
    except ProductCatalogError as exc:
        return error_response(str(exc), exc.status_code)
    tasks = [
        {
            "id": str(item.id),
            "title": f"{item.brand} · {item.name}",
            "productName": products.get(item.product_id, {}).get("name", item.product_id),
            "owner": item.reminder_owner,
            "expires": item.expires_on.isoformat(),
            "daysRemaining": (item.expires_on - today).days,
            "status": item.status,
        }
        for item in rows
    ]
    return JsonResponse(
        {
            "upcomingCount": sum(task["daysRemaining"] >= 0 for task in tasks),
            "expiredCount": sum(task["daysRemaining"] < 0 for task in tasks),
            "tasks": tasks,
        }
    )


@require_http_methods(["GET"])
def sidebar_metrics(request):
    access, error = request_access(request)
    if error:
        return error
    today = date.today()
    sync_expiry_statuses(today)
    submission_filter = Q(submitted_on__gte=today.replace(day=1), deleted_at__isnull=True)
    if not access.can_review:
        submission_filter &= submission_owner_filter(request)
    queryset = Submission.objects.filter(submission_filter)
    result = {
        "monthlySubmissions": queryset.count(),
        "pendingSubmissions": queryset.filter(status=SubmissionStatus.PENDING).count(),
    }
    if not access.can_review:
        result["needsInfoSubmissions"] = queryset.filter(
            status=SubmissionStatus.NEEDS_INFO
        ).count()
    elif access.can_manage:
        result["expiredSubmissions"] = Submission.objects.filter(
            deleted_at__isnull=True,
            status=SubmissionStatus.EXPIRED,
        ).count()
        result["totalCompetitors"] = Competitor.objects.filter(
            deleted_at__isnull=True
        ).count()
    return JsonResponse(result)
