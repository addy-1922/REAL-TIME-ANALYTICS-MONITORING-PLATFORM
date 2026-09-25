from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import Profile
from monitoring.models import AlertRule, AlertTrigger, Event, Project
from notifications.models import Notification

User = get_user_model()

PASSWORD = "TestPass123!"


def create_user(username="owner", email=None, password=PASSWORD, **extra):
    return User.objects.create_user(
        username=username,
        email=email or f"{username}@example.com",
        password=password,
        **extra,
    )


def create_project(owner, name="Test Project", api_key=None, **extra):
    if api_key is None:
        api_key = Project.generate_api_key()
    project = Project.objects.create(
        owner=owner,
        name=name,
        description=extra.pop("description", "Test project description"),
        api_key_hash=Project.hash_api_key(api_key),
        api_key_prefix=Project.key_prefix(api_key),
        **extra,
    )
    project.plaintext_api_key = api_key
    return project


def create_event(
    project,
    event_type=Event.EventType.API_REQUEST,
    status_code=200,
    response_time=120,
    service="api-gateway",
    environment="production",
    created_at=None,
    **extra,
):
    return Event.objects.create(
        project=project,
        event_type=event_type,
        custom_event_name=extra.pop("custom_event_name", ""),
        message=extra.pop("message", "Test event message"),
        service=service,
        environment=environment,
        status_code=status_code,
        response_time=response_time,
        metadata=extra.pop("metadata", {"path": "/api/test"}),
        created_at=created_at or timezone.now(),
        **extra,
    )


def create_alert_rule(project, **overrides):
    defaults = {
        "name": "Error count rule",
        "metric": AlertRule.Metric.ERROR_COUNT,
        "condition": AlertRule.Condition.GTE,
        "threshold": Decimal("5"),
        "time_window_minutes": 15,
        "cooldown_minutes": 0,
        "is_active": True,
    }
    defaults.update(overrides)
    return AlertRule.objects.create(project=project, **defaults)


def create_notification(user, project=None, **overrides):
    defaults = {
        "title": "Test notification",
        "message": "Test notification body",
        "notification_type": Notification.NotificationType.SYSTEM,
    }
    defaults.update(overrides)
    return Notification.objects.create(user=user, project=project, **defaults)


def create_profile(user, **overrides):
    profile, _ = Profile.objects.get_or_create(user=user)
    for key, value in overrides.items():
        setattr(profile, key, value)
    profile.save()
    return profile


def hours_ago(hours):
    return timezone.now() - timedelta(hours=hours)


__all__ = [
    "PASSWORD",
    "AlertTrigger",
    "create_alert_rule",
    "create_event",
    "create_notification",
    "create_profile",
    "create_project",
    "create_user",
    "hours_ago",
]
