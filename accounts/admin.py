from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "job_title",
        "timezone",
        "daily_report_enabled",
    )
    list_filter = ("daily_report_enabled", "timezone")
    list_select_related = ("user",)
    search_fields = ("user__username", "user__email", "job_title")
