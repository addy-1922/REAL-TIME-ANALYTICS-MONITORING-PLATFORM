from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("errors/", views.error_monitoring, name="error_monitoring"),
    path("errors/<int:event_id>/", views.error_detail, name="error_detail"),
    path("slow-requests/", views.slow_requests, name="slow_requests"),
]
