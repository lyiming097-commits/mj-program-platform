from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from identity_api.health import health_live, health_ready


urlpatterns = [
    path("api/health/", health_ready, name="health"),
    path("api/health/live", health_live, name="health_live"),
    path("api/health/ready", health_ready, name="health_ready"),
    path("api/", include("identity_api.urls")),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
