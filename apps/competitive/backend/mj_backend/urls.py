from django.urls import include, path

from competitive_vue_api.views import health, health_live, health_ready


urlpatterns = [
    path("api/health/", health, name="health"),
    path("api/health/live", health_live, name="health-live"),
    path("api/health/ready", health_ready, name="health-ready"),
    path("api/competitive/", include("competitive_vue_api.urls")),
]
