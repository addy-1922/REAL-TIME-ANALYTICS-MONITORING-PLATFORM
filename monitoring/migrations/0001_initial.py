import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Project",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                (
                    "api_key_hash",
                    models.CharField(
                        blank=True,
                        editable=False,
                        max_length=64,
                        null=True,
                        unique=True,
                    ),
                ),
                (
                    "api_key_prefix",
                    models.CharField(
                        blank=True,
                        editable=False,
                        max_length=64,
                        null=True,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="monitoring_projects",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="Event",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("API_REQUEST", "API Request"),
                            ("USER_LOGIN", "User Login"),
                            ("USER_LOGOUT", "User Logout"),
                            ("DATABASE_ERROR", "Database Error"),
                            ("APPLICATION_ERROR", "Application Error"),
                            ("PAYMENT", "Payment"),
                            ("ORDER", "Order"),
                            ("CUSTOM", "Custom"),
                        ],
                        max_length=64,
                    ),
                ),
                ("custom_event_name", models.CharField(blank=True, max_length=64)),
                ("message", models.TextField(blank=True)),
                ("service", models.CharField(blank=True, max_length=255)),
                ("environment", models.CharField(blank=True, max_length=64)),
                (
                    "response_time",
                    models.PositiveIntegerField(
                        blank=True,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(3600000),
                        ],
                    ),
                ),
                (
                    "status_code",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(100),
                            django.core.validators.MaxValueValidator(599),
                        ]
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("ip_address", models.CharField(blank=True, max_length=45)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="monitoring.project",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["project", "created_at"], name="mon_evt_proj_created"),
                    models.Index(fields=["project", "event_type", "created_at"], name="mon_evt_type_created"),
                    models.Index(fields=["project", "environment", "created_at"], name="mon_evt_env_created"),
                    models.Index(fields=["project", "status_code", "created_at"], name="mon_evt_status_created"),
                    models.Index(fields=["project", "service", "created_at"], name="mon_evt_service_created"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AlertRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                (
                    "metric",
                    models.CharField(
                        choices=[
                            ("ERROR_COUNT", "Error Count"),
                            ("ERROR_RATE", "Error Rate"),
                            ("AVG_RESPONSE_TIME", "Average Response Time"),
                        ],
                        max_length=64,
                    ),
                ),
                (
                    "condition",
                    models.CharField(
                        choices=[
                            ("GT", "Greater Than"),
                            ("GTE", "Greater Than Or Equal"),
                            ("LT", "Less Than"),
                            ("LTE", "Less Than Or Equal"),
                        ],
                        max_length=64,
                    ),
                ),
                ("threshold", models.DecimalField(decimal_places=4, max_digits=12)),
                ("time_window_minutes", models.PositiveIntegerField()),
                ("cooldown_minutes", models.PositiveIntegerField(default=60)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="alert_rules",
                        to="monitoring.project",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["project", "created_at"], name="mon_alert_created"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ActivityLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "project",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="activity_logs",
                        to="monitoring.project",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="monitoring_activity_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["user", "created_at"], name="mon_activity_user_created"),
                    models.Index(fields=["project", "created_at"], name="mon_activity_project_created"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AlertTrigger",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("message", models.TextField(blank=True)),
                ("metric_value", models.DecimalField(decimal_places=4, max_digits=12)),
                ("triggered_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="alert_triggers",
                        to="monitoring.project",
                    ),
                ),
                (
                    "rule",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="triggers",
                        to="monitoring.alertrule",
                    ),
                ),
            ],
            options={
                "ordering": ["-triggered_at", "-id"],
                "indexes": [
                    models.Index(fields=["project", "triggered_at"], name="mon_trigger_created"),
                    models.Index(fields=["rule", "triggered_at"], name="mon_trigger_rule_created"),
                ],
            },
        ),
    ]