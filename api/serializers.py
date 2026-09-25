import json
from datetime import date as Date
from datetime import datetime, time, timezone as datetime_timezone
from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from monitoring.models import AlertRule, Event, Project
from notifications.models import Notification


ENVIRONMENT_CHOICES = (
    "production",
    "staging",
    "development",
    "test",
    "qa",
    "local",
)
EVENT_TYPE_CHOICES = tuple(Event.EventType.choices)


class FlexibleDateTimeField(serializers.Field):
    default_error_messages = {
        "invalid": "Enter a valid ISO-8601 date or datetime.",
    }

    def to_internal_value(self, value):
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, Date):
            parsed = datetime.combine(value, time.min)
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                self.fail("invalid")
            if len(text) == 10:
                try:
                    parsed = datetime.combine(Date.fromisoformat(text), time.min)
                except ValueError as exc:
                    self.fail("invalid")
                    raise exc
            else:
                normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
                try:
                    parsed = datetime.fromisoformat(normalized)
                except (TypeError, ValueError) as exc:
                    self.fail("invalid")
                    raise exc
        else:
            self.fail("invalid")
            return None
        if timezone.is_naive(parsed):
            return timezone.make_aware(parsed, datetime_timezone.utc)
        return parsed.astimezone(datetime_timezone.utc)


class ProjectSerializer(serializers.ModelSerializer):
    owner = serializers.PrimaryKeyRelatedField(read_only=True)
    api_key_prefix = serializers.CharField(read_only=True, allow_null=True)
    api_key = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = (
            "id",
            "name",
            "description",
            "owner",
            "is_active",
            "api_key_prefix",
            "created_at",
            "updated_at",
            "api_key",
        )
        read_only_fields = (
            "id",
            "owner",
            "is_active",
            "api_key_prefix",
            "created_at",
            "updated_at",
        )

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Project name is required.")
        return value

    def create(self, validated_data):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise serializers.ValidationError("Authentication is required.")
        project, plaintext_key = Project.objects.create_with_api_key(
            owner=user,
            name=validated_data["name"],
            description=validated_data.get("description", ""),
        )
        project._plaintext_api_key = plaintext_key
        self.context["include_plaintext_api_key"] = True
        return project

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_api_key(self, obj):
        return getattr(obj, "_plaintext_api_key", None)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get("include_plaintext_api_key") or not hasattr(
            instance, "_plaintext_api_key"
        ):
            data.pop("api_key", None)
        return data


class EventSerializer(serializers.ModelSerializer):
    project = serializers.PrimaryKeyRelatedField(read_only=True)
    project_id = serializers.IntegerField(required=False, min_value=1)
    event_type = serializers.ChoiceField(choices=EVENT_TYPE_CHOICES, required=True)
    custom_event_name = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        trim_whitespace=True,
        max_length=64,
    )
    message = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        max_length=2000,
    )
    service = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        max_length=255,
    )
    environment = serializers.ChoiceField(
        choices=ENVIRONMENT_CHOICES,
        required=True,
    )
    response_time = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=3_600_000,
    )
    status_code = serializers.IntegerField(
        required=True,
        min_value=100,
        max_value=599,
    )
    metadata = serializers.JSONField(required=False, default=dict)
    ip_address = serializers.CharField(
        required=False,
        read_only=True,
        allow_blank=True,
        max_length=45,
    )
    id = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Event
        fields = (
            "id",
            "project",
            "project_id",
            "event_type",
            "custom_event_name",
            "message",
            "service",
            "environment",
            "response_time",
            "status_code",
            "metadata",
            "ip_address",
            "created_at",
        )
        read_only_fields = ("id", "ip_address", "created_at")

    def validate_custom_event_name(self, value):
        return value.strip() if value is not None else ""

    def validate_metadata(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Metadata must be a JSON object.")
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as exc:
            raise serializers.ValidationError(
                "Metadata must contain valid JSON values."
            ) from exc
        maximum = getattr(settings, "EVENT_METADATA_MAX_BYTES", 65_536)
        try:
            maximum = int(maximum)
        except (TypeError, ValueError):
            maximum = 65_536
        if len(encoded) > maximum:
            raise serializers.ValidationError(
                "Metadata exceeds the maximum allowed size."
            )
        return value

    def validate(self, attrs):
        event_type = attrs.get("event_type")
        custom_event_name = attrs.get("custom_event_name") or ""
        if event_type == Event.EventType.CUSTOM and not custom_event_name:
            raise serializers.ValidationError(
                {"custom_event_name": "This field is required for CUSTOM events."}
            )
        if event_type != Event.EventType.CUSTOM and custom_event_name:
            raise serializers.ValidationError(
                {
                    "custom_event_name": (
                        "This field is only allowed for CUSTOM events."
                    )
                }
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop("project_id", None)
        project = self.context.get("project")
        if project is None:
            raise serializers.ValidationError({"project": "A project is required."})
        validated_data["project"] = project
        return super().create(validated_data)


class AlertRuleSerializer(serializers.ModelSerializer):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.none())
    name = serializers.CharField(max_length=255, required=True)
    metric = serializers.ChoiceField(choices=AlertRule.Metric.choices, required=True)
    condition = serializers.ChoiceField(
        choices=AlertRule.Condition.choices,
        required=True,
    )
    threshold = serializers.DecimalField(
        max_digits=12,
        decimal_places=4,
        min_value=Decimal("0"),
        required=True,
    )
    time_window_minutes = serializers.IntegerField(min_value=1, required=True)
    cooldown_minutes = serializers.IntegerField(min_value=0, required=False, default=60)
    is_active = serializers.BooleanField(required=False, default=True)

    class Meta:
        model = AlertRule
        fields = (
            "id",
            "project",
            "name",
            "metric",
            "condition",
            "threshold",
            "time_window_minutes",
            "cooldown_minutes",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            self.fields["project"].queryset = Project.objects.filter(owner=user)

    def validate(self, attrs):
        project = attrs.get("project")
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if project is not None and user is not None and project.owner_id != user.pk:
            raise serializers.ValidationError(
                {"project": "Select a project you own."}
            )
        threshold = attrs.get("threshold")
        metric = attrs.get("metric")
        if (
            threshold is not None
            and metric == AlertRule.Metric.ERROR_RATE
            and threshold > 100
        ):
            raise serializers.ValidationError(
                {"threshold": "Error-rate thresholds must be between 0 and 100."}
            )
        return attrs


AlertSerializer = AlertRuleSerializer


class NotificationSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    project = serializers.PrimaryKeyRelatedField(read_only=True)
    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        model = Notification
        fields = (
            "id",
            "user",
            "project",
            "title",
            "message",
            "notification_type",
            "is_read",
            "created_at",
        )
        read_only_fields = ("id", "user", "project", "is_read", "created_at")


class EventFilterSerializer(serializers.Serializer):
    project = serializers.IntegerField(required=False, min_value=1)
    date_from = FlexibleDateTimeField(required=False)
    date_to = FlexibleDateTimeField(required=False)
    event_type = serializers.ChoiceField(
        choices=EVENT_TYPE_CHOICES,
        required=False,
    )
    service = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=255,
    )
    environment = serializers.ChoiceField(
        choices=ENVIRONMENT_CHOICES,
        required=False,
    )
    status_code = serializers.IntegerField(
        required=False,
        min_value=100,
        max_value=599,
    )
    slow = serializers.BooleanField(required=False)
    search = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=255,
    )

    def validate(self, attrs):
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError(
                {"date_to": "This value must be later than or equal to date_from."}
            )
        return attrs


class AnalyticsQuerySerializer(EventFilterSerializer):
    services = serializers.ListField(
        child=serializers.CharField(
            allow_blank=False,
            trim_whitespace=True,
            max_length=255,
        ),
        required=False,
        allow_empty=False,
    )

    def validate_services(self, value):
        services = []
        for item in value:
            services.extend(part.strip() for part in item.split(",") if part.strip())
        if not services:
            raise serializers.ValidationError("At least one service is required.")
        return list(dict.fromkeys(services))


class AnalyticsOverviewSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    today = serializers.IntegerField()
    week = serializers.IntegerField()
    month = serializers.IntegerField()
    errors = serializers.IntegerField()
    successes = serializers.IntegerField()
    error_rate = serializers.FloatField()
    avg_response_time = serializers.FloatField(allow_null=True)
    min_response_time = serializers.FloatField(allow_null=True)
    max_response_time = serializers.FloatField(allow_null=True)
    p50_response_time = serializers.FloatField(allow_null=True)
    p95_response_time = serializers.FloatField(allow_null=True)
    p99_response_time = serializers.FloatField(allow_null=True)


class AnalyticsGroupSerializer(serializers.Serializer):
    value = serializers.CharField(allow_null=True)
    count = serializers.IntegerField()


class AnalyticsTimelineSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField(allow_null=True)
    total = serializers.IntegerField()
    errors = serializers.IntegerField()
    successes = serializers.IntegerField()
    avg_response_time = serializers.FloatField(allow_null=True)


class AnalyticsResponseSerializer(serializers.Serializer):
    overview = AnalyticsOverviewSerializer()
    timeline = AnalyticsTimelineSerializer(many=True)
    event_types = AnalyticsGroupSerializer(many=True)
    services = AnalyticsGroupSerializer(many=True)
    environments = AnalyticsGroupSerializer(many=True)
    status_codes = AnalyticsGroupSerializer(many=True)
    project = serializers.DictField(allow_null=True)
    filters = serializers.DictField()


class ErrorBodySerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField()


class ErrorEnvelopeSerializer(serializers.Serializer):
    error = ErrorBodySerializer()
