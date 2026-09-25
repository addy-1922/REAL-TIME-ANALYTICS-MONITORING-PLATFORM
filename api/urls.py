from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny

from api.views import (
    AlertDetailView,
    AlertListCreateView,
    AnalyticsView,
    EventListCreateView,
    NotificationListView,
    NotificationReadView,
    ProjectDetailView,
    ProjectListCreateView,
)

app_name = "api"

urlpatterns = [
    path("events/", EventListCreateView.as_view(), name="events-list"),
    path("projects/", ProjectListCreateView.as_view(), name="projects-list"),
    path("projects/<int:pk>/", ProjectDetailView.as_view(), name="projects-detail"),
    path("analytics/", AnalyticsView.as_view(), name="analytics"),
    path("alerts/", AlertListCreateView.as_view(), name="alerts-list"),
    path("alerts/<int:pk>/", AlertDetailView.as_view(), name="alerts-detail"),
    path("notifications/", NotificationListView.as_view(), name="notifications-list"),
    path(
        "notifications/<int:pk>/read/",
        NotificationReadView.as_view(),
        name="notifications-read",
    ),
    path(
        "schema/",
        SpectacularAPIView.as_view(
            authentication_classes=[], permission_classes=[AllowAny]
        ),
        name="schema",
    ),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(
            url_name="api:schema",
            authentication_classes=[],
            permission_classes=[AllowAny],
        ),
        name="docs",
    ),
]
