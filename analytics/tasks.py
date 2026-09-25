from datetime import timedelta
from datetime import timezone as datetime_timezone
from smtplib import SMTPException

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import IntegrityError, OperationalError
from django.utils import timezone

from .models import DailyAnalyticsSummary
from .services import get_project_model, summarize_project


def _daily_report_users():
    user_model = get_user_model()
    users = user_model.objects.filter(is_active=True)
    try:
        user_model._meta.get_field("daily_report_enabled")
    except Exception:
        return [
            user
            for user in users
            if getattr(user, "daily_report_enabled", False)
            or getattr(getattr(user, "profile", None), "daily_report_enabled", False)
        ]
    return users.filter(daily_report_enabled=True)


@shared_task(
    autoretry_for=(OperationalError, IntegrityError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    default_retry_delay=60,
    acks_late=True,
)
def generate_daily_analytics_summaries():
    report_date = timezone.now().astimezone(datetime_timezone.utc).date() - timedelta(days=1)
    project_count = 0
    for project in get_project_model().objects.all().iterator():
        summarize_project(project, report_date)
        project_count += 1
    return {"date": report_date.isoformat(), "projects": project_count}


@shared_task(
    autoretry_for=(OperationalError, IntegrityError, SMTPException, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    default_retry_delay=60,
    acks_late=True,
)
def generate_daily_monitoring_reports():
    report_date = timezone.now().astimezone(datetime_timezone.utc).date() - timedelta(days=1)
    project_model = get_project_model()
    email_count = 0
    for user in _daily_report_users().iterator():
        projects = project_model.objects.filter(owner=user).iterator()
        summaries = []
        for project in projects:
            summary = DailyAnalyticsSummary.objects.filter(
                project=project,
                date=report_date,
            ).first()
            if summary is None:
                summary = summarize_project(project, report_date)
            summaries.append((project, summary))
        if not summaries or not user.email:
            continue
        body_lines = [f"Daily monitoring report for {report_date.isoformat()}", ""]
        for project, summary in summaries:
            body_lines.append(str(project))
            body_lines.append(
                f"Events: {summary.total_events}; errors: {summary.error_events}; "
                f"successes: {summary.success_events}; error rate: {summary.error_rate:.2f}%"
            )
            body_lines.append(
                "Response time (ms): "
                f"average {summary.avg_response_time if summary.avg_response_time is not None else 'n/a'}, "
                f"p50 {summary.p50_response_time if summary.p50_response_time is not None else 'n/a'}, "
                f"p95 {summary.p95_response_time if summary.p95_response_time is not None else 'n/a'}, "
                f"p99 {summary.p99_response_time if summary.p99_response_time is not None else 'n/a'}"
            )
            body_lines.append("")
        send_mail(
            subject=f"Daily monitoring report — {report_date.isoformat()}",
            message="\n".join(body_lines),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        email_count += 1
    return {"date": report_date.isoformat(), "emails_sent": email_count}
