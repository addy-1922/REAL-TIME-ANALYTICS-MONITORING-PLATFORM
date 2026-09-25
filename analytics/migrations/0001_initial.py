from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("monitoring", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DailyAnalyticsSummary",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("date", models.DateField()),
                ("total_events", models.PositiveIntegerField(default=0)),
                ("error_events", models.PositiveIntegerField(default=0)),
                ("success_events", models.PositiveIntegerField(default=0)),
                ("error_rate", models.FloatField(default=0)),
                ("avg_response_time", models.FloatField(blank=True, null=True)),
                ("min_response_time", models.FloatField(blank=True, null=True)),
                ("max_response_time", models.FloatField(blank=True, null=True)),
                ("p50_response_time", models.FloatField(blank=True, null=True)),
                ("p95_response_time", models.FloatField(blank=True, null=True)),
                ("p99_response_time", models.FloatField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="daily_analytics_summaries",
                        to="monitoring.project",
                    ),
                ),
            ],
            options={
                "ordering": ("-date",),
                "unique_together": {("project", "date")},
            },
        ),
    ]
