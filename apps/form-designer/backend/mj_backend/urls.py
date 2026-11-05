from django.urls import include, path
from form_designer_api.views import health
urlpatterns = [
    path('api/form-designer/', include('form_designer_api.urls')),
    path('api/health/ready', health),
    path('api/health/live', health),
]
