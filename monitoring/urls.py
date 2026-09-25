from django.urls import path

from . import views

app_name = "monitoring"

urlpatterns = [
    path("", views.ProjectListView.as_view(), name="project_list"),
    path("new/", views.ProjectCreateView.as_view(), name="project_create"),
    path("<int:pk>/", views.ProjectDetailView.as_view(), name="project_detail"),
    path(
        "<int:pk>/dashboard/",
        views.ProjectDashboardView.as_view(),
        name="project_dashboard",
    ),
    path("<int:pk>/edit/", views.ProjectEditView.as_view(), name="project_edit"),
    path("<int:pk>/delete/", views.ProjectDeleteView.as_view(), name="project_delete"),
    path(
        "<int:pk>/regenerate-key/",
        views.project_regenerate_key,
        name="project_regenerate_key",
    ),
    path("<int:pk>/events/", views.EventListView.as_view(), name="event_list"),
    path(
        "<int:pk>/events/export/",
        views.event_export,
        name="event_export",
    ),
    path(
        "<int:pk>/events/<int:event_pk>/",
        views.EventDetailView.as_view(),
        name="event_detail",
    ),
    path("<int:pk>/alerts/", views.AlertRuleListView.as_view(), name="alert_list"),
    path(
        "<int:pk>/alerts/new/",
        views.AlertRuleCreateView.as_view(),
        name="alert_create",
    ),
    path(
        "<int:pk>/alerts/<int:alert_pk>/toggle/",
        views.alert_toggle,
        name="alert_toggle",
    ),
    path("activity/", views.ActivityLogListView.as_view(), name="activity_list"),
]