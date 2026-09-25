import math
import operator
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import partial

from celery import shared_task
from django.conf import settings
from django.db import DatabaseError, OperationalError, transaction
from django.db.models import Avg, Q
from django.utils import timezone

from monitoring.models import AlertRule, AlertTrigger, Event, Project
from notifications.models import Notification
from notifications.services import create_notification


ERROR_EVENT_TYPES = set(Event.ERROR_EVENT_TYPES)
COMPARATORS = {
    AlertRule.Condition.GT: operator.gt,
    AlertRule.Condition.GTE: operator.ge,
    AlertRule.Condition.LT: operator.lt,
    AlertRule.Condition.LTE: operator.le,
}
SPIKE_TITLE = "Abnormal error spike"
DECIMAL_QUANTUM = Decimal("0.0001")


def _error_query():
    return Q(status_code__gte=400) | Q(event_type__in=ERROR_EVENT_TYPES)


def _decimal_value(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite():
        return None
    return number.quantize(DECIMAL_QUANTUM, rounding=ROUND_HALF_UP)


def _condition_matches(condition, value, threshold):
    comparator = COMPARATORS.get(condition)
    if comparator is None or value is None:
        return False
    return comparator(value, Decimal(str(threshold)))


def _enqueue_email(notification_id):
    try:
        from notifications.tasks import send_notification_email

        send_notification_email.delay(notification_id)
    except Exception:
        return False
    return True


def _event_marker(event_id):
    return f"[event:{event_id}]"


def _create_rule_trigger(rule, event, metric_value):
    now = timezone.now()
    marker = _event_marker(event.pk)
    metric_value = _decimal_value(metric_value)
    if metric_value is None:
        return False

    with transaction.atomic():
        locked_rule = AlertRule.objects.select_for_update().get(pk=rule.pk)
        if not locked_rule.is_active:
            return False
        if AlertTrigger.objects.filter(
            rule_id=locked_rule.pk,
            project_id=event.project_id,
            message__contains=marker,
        ).exists():
            return False
        cooldown = max(0, int(locked_rule.cooldown_minutes or 0))
        if cooldown:
            cutoff = now - timedelta(minutes=cooldown)
            if AlertTrigger.objects.filter(
                rule_id=locked_rule.pk,
                project_id=event.project_id,
                triggered_at__gte=cutoff,
            ).exists():
                return False

        trigger = AlertTrigger.objects.create(
            rule=locked_rule,
            project_id=event.project_id,
            title=f"{locked_rule.name} triggered",
            message=(
                f"{locked_rule.get_metric_display()} was "
                f"{metric_value} for project {event.project_id}. {marker}"
            ),
            metric_value=metric_value,
            triggered_at=now,
        )
        notification = create_notification(
            user_id=event.project.owner_id,
            project_id=event.project_id,
            title=trigger.title,
            message=trigger.message,
            notification_type=(
                Notification.NotificationType.ERROR_ALERT
                if locked_rule.metric
                in {AlertRule.Metric.ERROR_COUNT, AlertRule.Metric.ERROR_RATE}
                else Notification.NotificationType.PERFORMANCE_ALERT
            ),
        )
        transaction.on_commit(partial(_enqueue_email, notification.pk))
    return True


def _rule_metric_value(rule, window):
    if rule.metric == AlertRule.Metric.ERROR_COUNT:
        return window.filter(_error_query()).count()
    if rule.metric == AlertRule.Metric.ERROR_RATE:
        total = window.count()
        if not total:
            return 0.0
        return window.filter(_error_query()).count() / total * 100
    if rule.metric == AlertRule.Metric.AVG_RESPONSE_TIME:
        return window.aggregate(value=Avg("response_time"))["value"]
    return None


@shared_task(
    autoretry_for=(OperationalError, DatabaseError),
    retry_backoff=True,
    max_retries=3,
)
def process_event(event_id):
    try:
        event = Event.objects.select_related("project__owner").get(pk=event_id)
    except Event.DoesNotExist:
        return {"event_id": event_id, "triggers_created": 0}

    now = timezone.now()
    rules = AlertRule.objects.filter(
        project_id=event.project_id,
        is_active=True,
    ).select_related("project")
    triggers_created = 0
    for rule in rules:
        window = Event.objects.filter(
            project_id=event.project_id,
            created_at__gte=now - timedelta(minutes=max(1, int(rule.time_window_minutes))),
            created_at__lte=now,
        )
        value = _rule_metric_value(rule, window)
        if _condition_matches(rule.condition, value, rule.threshold):
            if _create_rule_trigger(rule, event, value):
                triggers_created += 1
    return {"event_id": event_id, "triggers_created": triggers_created}


def _spike_setting(name, default):
    try:
        value = float(getattr(settings, name, default))
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(value) or value < 0:
        return float(default)
    return value


def _spike_marker(now):
    bucket = int(now.timestamp() // 300)
    return f"[spike:{bucket}]"


def _create_spike_trigger(project, current_errors, previous_errors, now):
    multiplier = _spike_setting("ERROR_SPIKE_MULTIPLIER", 3)
    cooldown_minutes = _spike_setting("ERROR_SPIKE_COOLDOWN_MINUTES", 5)
    marker = _spike_marker(now)
    with transaction.atomic():
        locked_project = Project.objects.select_for_update().get(pk=project.pk)
        duplicate = AlertTrigger.objects.filter(
            project_id=locked_project.pk,
            rule__isnull=True,
            title=SPIKE_TITLE,
            message__contains=marker,
        )
        if duplicate.exists():
            return False
        if cooldown_minutes and AlertTrigger.objects.filter(
            project_id=locked_project.pk,
            rule__isnull=True,
            title=SPIKE_TITLE,
            triggered_at__gte=now - timedelta(minutes=cooldown_minutes),
        ).exists():
            return False
        trigger = AlertTrigger.objects.create(
            project=locked_project,
            rule=None,
            title=SPIKE_TITLE,
            message=(
                f"Errors increased from {previous_errors} to {current_errors} "
                f"in the last five minutes (threshold multiplier {multiplier}). "
                f"{marker}"
            ),
            metric_value=_decimal_value(current_errors),
            triggered_at=now,
        )
        notification = create_notification(
            user_id=locked_project.owner_id,
            project_id=locked_project.pk,
            title=trigger.title,
            message=trigger.message,
            notification_type=Notification.NotificationType.ERROR_ALERT,
        )
        transaction.on_commit(partial(_enqueue_email, notification.pk))
    return True


@shared_task(
    autoretry_for=(OperationalError, DatabaseError),
    retry_backoff=True,
    max_retries=3,
)
def detect_abnormal_error_spikes():
    now = timezone.now()
    threshold = _spike_setting("ERROR_SPIKE_THRESHOLD", 5)
    multiplier = _spike_setting("ERROR_SPIKE_MULTIPLIER", 3)
    current_start = now - timedelta(minutes=5)
    previous_start = now - timedelta(minutes=10)
    projects = Project.objects.filter(is_active=True)
    triggers_created = 0
    for project in projects:
        current_errors = Event.objects.filter(
            project_id=project.pk,
            created_at__gte=current_start,
            created_at__lt=now,
        ).filter(_error_query()).count()
        previous_errors = Event.objects.filter(
            project_id=project.pk,
            created_at__gte=previous_start,
            created_at__lt=current_start,
        ).filter(_error_query()).count()
        if (
            current_errors >= threshold
            and current_errors > previous_errors
            and current_errors >= previous_errors * multiplier
        ):
            if _create_spike_trigger(
                project,
                current_errors,
                previous_errors,
                now,
            ):
                triggers_created += 1
    return {"projects_scanned": projects.count(), "triggers_created": triggers_created}


@shared_task(
    autoretry_for=(OperationalError, DatabaseError),
    retry_backoff=True,
    max_retries=3,
)
def cleanup_old_events(retention_days=None):
    if retention_days is None:
        retention_days = settings.EVENT_RETENTION_DAYS
    cutoff = timezone.now() - timedelta(days=max(0, int(retention_days)))
    batch_size = 1000
    deleted_total = 0
    while True:
        ids = list(
            Event.objects.filter(created_at__lt=cutoff)
            .values_list("id", flat=True)
            .order_by("id")[:batch_size]
        )
        if not ids:
            break
        deleted_total += Event.objects.filter(id__in=ids).delete()[0]
    return {"deleted_event_count": deleted_total}
