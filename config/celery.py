import os
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("analytics_platform")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=300,
    task_time_limit=360,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "generate-daily-analytics": {
            "task": "analytics.tasks.generate_daily_analytics_summaries",
            "schedule": crontab(hour=0, minute=15),
        },
        "generate-daily-reports": {
            "task": "analytics.tasks.generate_daily_monitoring_reports",
            "schedule": crontab(hour=7, minute=0),
        },
        "detect-error-spikes": {
            "task": "monitoring.tasks.detect_abnormal_error_spikes",
            "schedule": timedelta(minutes=5),
        },
        "cleanup-old-events": {
            "task": "monitoring.tasks.cleanup_old_events",
            "schedule": crontab(hour=2, minute=30),
        },
    },
)
