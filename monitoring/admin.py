from django.contrib import admin

from .models import ActivityLog, AlertRule, AlertTrigger, Event, Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "api_key_prefix",
        "is_active",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "owner__username")
    list_select_related = ("owner",)
    readonly_fields = ("api_key_hash", "api_key_prefix", "created_at", "updated_at")
    ordering = ("-created_at",)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project",
        "display_event_type",
        "service",
        "environment",
        "status_code",
        "response_time",
        "created_at",
    )
    list_filter = ("event_type", "environment", "service", "status_code", "created_at")
    search_fields = (
        "message",
        "service",
        "environment",
        "custom_event_name",
        "ip_address",
        "project__name",
    )
    list_select_related = ("project",)
    autocomplete_fields = ("project",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "project",
        "metric",
        "condition",
        "threshold",
        "time_window_minutes",
        "is_active",
    )
    list_filter = ("metric", "condition", "is_active")
    search_fields = ("name", "project__name")
    list_select_related = ("project",)
    autocomplete_fields = ("project",)


@admin.register(AlertTrigger)
class AlertTriggerAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "rule", "metric_value", "triggered_at")
    list_filter = ("triggered_at",)
    search_fields = ("title", "message", "project__name")
    list_select_related = ("project", "rule")
    autocomplete_fields = ("project", "rule")
    readonly_fields = ("triggered_at",)


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "project", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("user__username", "action", "description")
    list_select_related = ("user", "project")
    date_hierarchy = "created_at"
    readonly_fields = ("user", "project", "action", "description", "created_at")

    def has_add_permission(self, request):
        return False