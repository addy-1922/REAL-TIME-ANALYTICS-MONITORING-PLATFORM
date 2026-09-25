from django.apps import apps
from django.core.exceptions import ValidationError

from .services import error_q, filter_events, response_time_field


class AnalyticsFilters:
    fields = (
        "project",
        "date_from",
        "date_to",
        "event_type",
        "service",
        "environment",
        "status_code",
        "search",
    )

    def __init__(self, user, data=None):
        self.user = user
        self.data = data or {}

    def apply(self, queryset):
        values = {field: self.data.get(field) for field in self.fields}
        return filter_events(queryset, **values)

    @property
    def project(self):
        return self.data.get("project")

    @property
    def date_from(self):
        return self.data.get("date_from")

    @property
    def date_to(self):
        return self.data.get("date_to")


class ErrorMonitoringFilters(AnalyticsFilters):
    fields = ("project", "date_from", "date_to", "service", "environment")

    def apply(self, queryset):
        values = {field: self.data.get(field) for field in self.fields}
        return filter_events(queryset, **values).filter(error_q())


class SlowRequestFilters(AnalyticsFilters):
    fields = ("project", "date_from", "date_to", "search")

    def apply(self, queryset, threshold):
        values = {field: self.data.get(field) for field in self.fields}
        field_name = response_time_field(queryset)
        if not field_name:
            return queryset.none()
        return filter_events(queryset, **values).filter(
            **{f"{field_name}__gte": threshold}
        )


AnalyticsFilter = AnalyticsFilters
ErrorMonitoringFilter = ErrorMonitoringFilters
SlowRequestsFilter = SlowRequestFilters


def validate_project_owner(user, project):
    if project is None:
        return None
    project_model = apps.get_model("monitoring", "Project")
    if getattr(project, "owner_id", None) == user.pk:
        return project
    try:
        return project_model.objects.get(pk=project, owner=user)
    except (project_model.DoesNotExist, ValueError, TypeError) as exc:
        raise ValidationError("The selected project is unavailable") from exc
