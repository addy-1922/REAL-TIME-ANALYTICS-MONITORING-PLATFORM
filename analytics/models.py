from django.db import models


class DailyAnalyticsSummary(models.Model):
    project = models.ForeignKey(
        "monitoring.Project",
        on_delete=models.CASCADE,
        related_name="daily_analytics_summaries",
    )
    date = models.DateField()
    total_events = models.PositiveIntegerField(default=0)
    error_events = models.PositiveIntegerField(default=0)
    success_events = models.PositiveIntegerField(default=0)
    error_rate = models.FloatField(default=0)
    avg_response_time = models.FloatField(null=True, blank=True)
    min_response_time = models.FloatField(null=True, blank=True)
    max_response_time = models.FloatField(null=True, blank=True)
    p50_response_time = models.FloatField(null=True, blank=True)
    p95_response_time = models.FloatField(null=True, blank=True)
    p99_response_time = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date",)
        unique_together = (("project", "date"),)

    def __str__(self):
        return f"{self.project} — {self.date}"
