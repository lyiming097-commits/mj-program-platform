from django.urls import path
from .views import endpoint
urlpatterns = [path('', endpoint), path('<path:resource>', endpoint)]
