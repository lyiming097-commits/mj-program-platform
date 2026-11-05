from django.conf import settings
import mimetypes
from pathlib import Path

from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404, JsonResponse
from django.urls import include, path
from django.utils._os import safe_join


def health(request):
    return JsonResponse({"ok": True, "service": "cable-mall-backend"})


def cable_mall_media(request, relative_path):
    clean_path = str(relative_path or "").strip().lstrip("/")
    if request.method not in {"GET", "HEAD"} or not clean_path.startswith("cable_mall/product_thumbs/"):
        raise Http404
    try:
        disk_path = Path(safe_join(settings.MEDIA_ROOT, clean_path))
    except SuspiciousFileOperation as exc:
        raise Http404 from exc
    if not disk_path.is_file():
        raise Http404
    content_type = mimetypes.guess_type(disk_path.name)[0] or "application/octet-stream"
    response = FileResponse(open(disk_path, "rb"), content_type=content_type)
    response["Cache-Control"] = "public, max-age=86400"
    return response


urlpatterns = [
    path("api/health/", health, name="health"),
    path("api/", include("cable_mall.urls")),
    path("cable-mall-media/<path:relative_path>", cable_mall_media, name="cable_mall_media"),
]
