from django.contrib import admin

from .models import DailyAnalyticsSummary


@admin.register(DailyAnalyticsSummary)
class DailyAnalyticsSummaryAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "date",
        "total_events",
        "error_events",
        "success_events",
        "error_rate",
        "avg_response_time",
        "p95_response_time",
    )
    list_filter = ("date",)
    search_fields = ("project__name",)
    date_hierarchy = "date"
    readonly_fields = ("created_at", "updated_at")
