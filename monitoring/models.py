import hashlib
import hmac
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class ProjectManager(models.Manager):
    def create_with_api_key(self, *, owner, name, description=""):
        api_key = Project.generate_api_key()
        return (
            self.create(
                owner=owner,
                name=name,
                description=description,
                api_key_hash=Project.hash_api_key(api_key),
                api_key_prefix=Project.key_prefix(api_key),
            ),
            api_key,
        )

    def authenticate_api_key(self, api_key):
        candidate_hash = Project.hash_api_key(api_key)
        for project in self.filter(is_active=True).exclude(api_key_hash__isnull=True):
            if hmac.compare_digest(str(project.api_key_hash), candidate_hash):
                return project
        return None


class Project(models.Model):
    KEY_PREFIX = "rt_live_"

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="monitoring_projects",
    )
    api_key_hash = models.CharField(
        max_length=64, unique=True, null=True, blank=True, editable=False
    )
    api_key_prefix = models.CharField(
        max_length=64, null=True, blank=True, editable=False
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProjectManager()

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.name

    @classmethod
    def generate_api_key(cls):
        selector = secrets.token_urlsafe(32)
        secret = secrets.token_urlsafe(32)
        return f"{cls.KEY_PREFIX}{selector}.{secret}"

    @classmethod
    def hash_api_key(cls, api_key):
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    @classmethod
    def key_prefix(cls, api_key):
        if api_key is None or not api_key.startswith(cls.KEY_PREFIX):
            return None
        return api_key[: api_key.rfind(".")]

    def rotate_api_key(self):
        api_key = self.generate_api_key()
        self.api_key_hash = self.hash_api_key(api_key)
        self.api_key_prefix = self.key_prefix(api_key)
        self.save(update_fields=["api_key_hash", "api_key_prefix", "updated_at"])
        return api_key

    def revoke_api_key(self):
        self.api_key_hash = None
        self.api_key_prefix = None
        self.save(update_fields=["api_key_hash", "api_key_prefix", "updated_at"])

    def authenticate_api_key(self, api_key):
        if not self.api_key_hash or not api_key:
            return False
        candidate_hash = self.hash_api_key(api_key)
        return hmac.compare_digest(str(self.api_key_hash), candidate_hash)

    def verify_api_key(self, api_key):
        return self.authenticate_api_key(api_key)


class Event(models.Model):
    class EventType(models.TextChoices):
        API_REQUEST = "API_REQUEST", "API Request"
        USER_LOGIN = "USER_LOGIN", "User Login"
        USER_LOGOUT = "USER_LOGOUT", "User Logout"
        DATABASE_ERROR = "DATABASE_ERROR", "Database Error"
        APPLICATION_ERROR = "APPLICATION_ERROR", "Application Error"
        PAYMENT = "PAYMENT", "Payment"
        ORDER = "ORDER", "Order"
        CUSTOM = "CUSTOM", "Custom"

    ERROR_EVENT_TYPES = {
        EventType.DATABASE_ERROR.value,
        EventType.APPLICATION_ERROR.value,
    }

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=64, choices=EventType.choices)
    custom_event_name = models.CharField(max_length=64, blank=True)
    message = models.TextField(blank=True)
    service = models.CharField(max_length=255, blank=True)
    environment = models.CharField(max_length=64, blank=True)
    response_time = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(3_600_000)],
    )
    status_code = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(100), MaxValueValidator(599)]
    )
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.CharField(max_length=45, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["project", "created_at"],
                name="mon_evt_proj_created",
            ),
            models.Index(
                fields=["project", "event_type", "created_at"],
                name="mon_evt_type_created",
            ),
            models.Index(
                fields=["project", "environment", "created_at"],
                name="mon_evt_env_created",
            ),
            models.Index(
                fields=["project", "status_code", "created_at"],
                name="mon_evt_status_created",
            ),
            models.Index(
                fields=["project", "service", "created_at"],
                name="mon_evt_service_created",
            ),
        ]

    def __str__(self):
        return f"{self.display_event_type} - {self.project_id}"

    def clean(self):
        super().clean()
        if self.event_type == self.EventType.CUSTOM and not self.custom_event_name:
            raise ValidationError(
                {"custom_event_name": "custom_event_name is required for CUSTOM events."}
            )
        if self.event_type != self.EventType.CUSTOM and self.custom_event_name:
            raise ValidationError(
                {
                    "custom_event_name": (
                        "custom_event_name is only allowed for CUSTOM events."
                    )
                }
            )

    @property
    def display_event_type(self):
        if self.event_type == self.EventType.CUSTOM:
            return self.custom_event_name
        return self.get_event_type_display()

    @property
    def is_error(self):
        if self.event_type in self.ERROR_EVENT_TYPES:
            return True
        return self.status_code is not None and self.status_code >= 400

    @property
    def is_success(self):
        if self.is_error:
            return False
        return self.status_code is not None and 200 <= self.status_code < 400

    @property
    def is_slow(self):
        if self.response_time is None:
            return False
        return self.response_time > settings.SLOW_REQUEST_THRESHOLD


class AlertRule(models.Model):
    class Metric(models.TextChoices):
        ERROR_COUNT = "ERROR_COUNT", "Error Count"
        ERROR_RATE = "ERROR_RATE", "Error Rate"
        AVG_RESPONSE_TIME = "AVG_RESPONSE_TIME", "Average Response Time"

    class Condition(models.TextChoices):
        GT = "GT", "Greater Than"
        GTE = "GTE", "Greater Than Or Equal"
        LT = "LT", "Less Than"
        LTE = "LTE", "Less Than Or Equal"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="alert_rules"
    )
    name = models.CharField(max_length=255)
    metric = models.CharField(max_length=64, choices=Metric.choices)
    condition = models.CharField(max_length=64, choices=Condition.choices)
    threshold = models.DecimalField(max_digits=12, decimal_places=4)
    time_window_minutes = models.PositiveIntegerField()
    cooldown_minutes = models.PositiveIntegerField(default=60)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["project", "created_at"],
                name="mon_alert_created",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.time_window_minutes is not None and self.time_window_minutes < 1:
            raise ValidationError(
                {"time_window_minutes": "time_window_minutes must be at least 1."}
            )
        if self.cooldown_minutes is not None and self.cooldown_minutes < 0:
            raise ValidationError(
                {"cooldown_minutes": "cooldown_minutes must be zero or greater."}
            )


class AlertTrigger(models.Model):
    rule = models.ForeignKey(
        AlertRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggers",
    )
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="alert_triggers"
    )
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    metric_value = models.DecimalField(max_digits=12, decimal_places=4)
    triggered_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-triggered_at", "-id"]
        indexes = [
            models.Index(
                fields=["project", "triggered_at"],
                name="mon_trigger_created",
            ),
            models.Index(
                fields=["rule", "triggered_at"],
                name="mon_trigger_rule_created",
            ),
        ]

    def __str__(self):
        return self.title


class ActivityLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="monitoring_activity_logs",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    action = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["user", "created_at"],
                name="mon_activity_user_created",
            ),
            models.Index(
                fields=["project", "created_at"],
                name="mon_activity_project_created",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.action}"