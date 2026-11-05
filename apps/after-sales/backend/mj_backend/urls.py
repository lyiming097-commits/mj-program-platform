from django.urls import include, path

from after_sales_api.views import health, health_live, health_ready


urlpatterns = [
    path("api/health/", health, name="health"),
    path("api/health/live", health_live, name="health-live"),
    path("api/health/ready", health_ready, name="health-ready"),
    path("api/after-sales/", include("after_sales_api.urls")),
]
