import re
from collections.abc import Mapping
from functools import partial
from ipaddress import ip_address

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics, permissions, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics import services as analytics_services
from api.auth import APIKeyAuthentication
from api.pagination import StandardResultsSetPagination
from api.serializers import (
    AlertRuleSerializer,
    AnalyticsQuerySerializer,
    AnalyticsResponseSerializer,
    ErrorEnvelopeSerializer,
    EventFilterSerializer,
    EventSerializer,
    NotificationSerializer,
    ProjectSerializer,
)
from monitoring.models import AlertRule, Event, Project
from notifications.models import Notification


EVENT_ORDERING_FIELDS = (
    "created_at",
    "event_type",
    "service",
    "environment",
    "response_time",
    "status_code",
)
PROJECT_ORDERING_FIELDS = ("name", "created_at", "updated_at")
ALERT_ORDERING_FIELDS = ("created_at", "name", "is_active")
NOTIFICATION_ORDERING_FIELDS = ("created_at", "is_read")


def _preserve_date_only_values(filters, query_params):
    for field in ("date_from", "date_to"):
        value = query_params.get(field)
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            filters[field] = value
    return filters


def _client_ip(request):
    candidates = (
        request.META.get("HTTP_X_FORWARDED_FOR", "").split(",", 1)[0].strip(),
        request.META.get("HTTP_X_REAL_IP", "").strip(),
        request.META.get("REMOTE_ADDR", "").strip(),
    )
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return str(ip_address(candidate))
        except ValueError:
            continue
    return ""


def _error_responses(*status_codes):
    return {
        code: OpenApiResponse(response=ErrorEnvelopeSerializer)
        for code in status_codes
    }


def _invalidate_analytics(project):
    return analytics_services.increment_cache_version(project=project)


def _enqueue_process_event(event_id):
    from monitoring.tasks import process_event

    process_event.delay(event_id)


def _after_event_commit(event_id):
    try:
        event = Event.objects.select_related("project").get(pk=event_id)
    except Event.DoesNotExist:
        return

    try:
        payload = {
            "type": "monitoring.event",
            "event": EventSerializer(event).data,
        }
        channel_layer = get_channel_layer()
        if channel_layer is not None:
            async_to_sync(channel_layer.group_send)(
                f"monitoring_project_{event.project_id}",
                payload,
            )
    except Exception:
        pass

    try:
        _invalidate_analytics(event.project)
    except Exception:
        pass

    try:
        _enqueue_process_event(event.pk)
    except Exception:
        pass


class EventListCreateView(generics.ListAPIView):
    serializer_class = EventSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [OrderingFilter]
    ordering_fields = EVENT_ORDERING_FIELDS
    ordering = ("-created_at", "-id")

    def get_authenticators(self):
        if getattr(self.request, "method", None) == "POST":
            return [APIKeyAuthentication()]
        return super().get_authenticators()

    def get_permissions(self):
        if getattr(self.request, "method", None) == "POST":
            return [permissions.AllowAny()]
        return super().get_permissions()

    def get_queryset(self):
        queryset = Event.objects.filter(
            project__owner=self.request.user
        ).select_related("project")
        if not hasattr(self, "_event_filters"):
            filter_serializer = EventFilterSerializer(
                data=self.request.query_params
            )
            filter_serializer.is_valid(raise_exception=True)
            self._event_filters = _preserve_date_only_values(
                dict(filter_serializer.validated_data),
                self.request.query_params,
            )
        return analytics_services.filter_events(queryset, **self._event_filters)

    @extend_schema(
        tags=["Events"],
        parameters=[
            OpenApiParameter("project", int, required=False),
            OpenApiParameter("date_from", str, required=False),
            OpenApiParameter("date_to", str, required=False),
            OpenApiParameter("event_type", str, required=False),
            OpenApiParameter("service", str, required=False),
            OpenApiParameter("environment", str, required=False),
            OpenApiParameter("status_code", int, required=False),
            OpenApiParameter("slow", bool, required=False),
            OpenApiParameter("search", str, required=False),
            OpenApiParameter("ordering", str, required=False),
            OpenApiParameter("page", int, required=False),
            OpenApiParameter("page_size", int, required=False),
        ],
        responses={200: EventSerializer(many=True), **_error_responses(400, 403)},
    )
    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    @extend_schema(
        tags=["Events"],
        request=EventSerializer,
        responses={
            201: EventSerializer,
            **_error_responses(400, 401, 403),
        },
    )
    def post(self, request):
        project = request.auth
        if not isinstance(project, Project) or not project.is_active:
            raise PermissionDenied("The authenticated project is unavailable.")

        if not isinstance(request.data, Mapping):
            raise DRFValidationError(
                {"non_field_errors": ["Expected a JSON object."]}
            )

        if "project_id" in request.data:
            raw_project_id = request.data.get("project_id")
            try:
                if isinstance(raw_project_id, bool):
                    raise ValueError
                project_id = int(raw_project_id)
            except (TypeError, ValueError, OverflowError) as exc:
                raise PermissionDenied(
                    "The project does not match the authenticated API key."
                ) from exc
            if project_id != project.pk:
                raise PermissionDenied(
                    "The project does not match the authenticated API key."
                )

        serializer = EventSerializer(
            data=request.data,
            context={"request": request, "project": project},
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            event = serializer.save(
                project=project,
                ip_address=_client_ip(request),
            )
            transaction.on_commit(partial(_after_event_commit, event.pk))
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(
        tags=["Projects"],
        responses={200: ProjectSerializer(many=True), **_error_responses(403)},
    ),
    post=extend_schema(
        tags=["Projects"],
        request=ProjectSerializer,
        responses={201: ProjectSerializer, **_error_responses(400, 403)},
    ),
)
class ProjectListCreateView(generics.ListCreateAPIView):
    serializer_class = ProjectSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [OrderingFilter]
    ordering_fields = PROJECT_ORDERING_FIELDS
    ordering = ("-created_at", "-id")

    def get_queryset(self):
        return Project.objects.filter(owner=self.request.user).order_by(
            "-created_at", "-id"
        )


@extend_schema_view(
    get=extend_schema(
        tags=["Projects"],
        responses={200: ProjectSerializer, **_error_responses(403, 404)},
    )
)
class ProjectDetailView(generics.RetrieveAPIView):
    serializer_class = ProjectSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Project.objects.filter(owner=self.request.user)


class AnalyticsView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["Analytics"],
        parameters=[
            OpenApiParameter("project", int, required=False),
            OpenApiParameter("date_from", str, required=False),
            OpenApiParameter("date_to", str, required=False),
            OpenApiParameter("event_type", str, required=False),
            OpenApiParameter("service", str, required=False),
            OpenApiParameter("environment", str, required=False),
            OpenApiParameter("status_code", int, required=False),
            OpenApiParameter("slow", bool, required=False),
            OpenApiParameter("search", str, required=False),
        ],
        responses={200: AnalyticsResponseSerializer, **_error_responses(400, 403)},
    )
    def get(self, request):
        parameters = {}
        for key in (
            "project",
            "date_from",
            "date_to",
            "event_type",
            "service",
            "environment",
            "status_code",
            "slow",
            "search",
        ):
            if key in request.query_params:
                parameters[key] = request.query_params.get(key)
        if "services" in request.query_params:
            parameters["services"] = request.query_params.getlist("services")
        serializer = AnalyticsQuerySerializer(data=parameters)
        serializer.is_valid(raise_exception=True)
        filters = _preserve_date_only_values(
            dict(serializer.validated_data),
            request.query_params,
        )
        project = filters.pop("project", None)
        data = analytics_services.dashboard_data(
            request.user,
            project=project,
            filters=filters,
        )
        return Response(data)


@extend_schema_view(
    get=extend_schema(
        tags=["Alerts"],
        parameters=[OpenApiParameter("project", int, required=False)],
        responses={200: AlertRuleSerializer(many=True), **_error_responses(403)},
    ),
    post=extend_schema(
        tags=["Alerts"],
        request=AlertRuleSerializer,
        responses={201: AlertRuleSerializer, **_error_responses(400, 403)},
    ),
)
class AlertListCreateView(generics.ListCreateAPIView):
    serializer_class = AlertRuleSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [filters.DjangoFilterBackend, OrderingFilter]
    filterset_fields = {"project": ["exact"]}
    ordering_fields = ALERT_ORDERING_FIELDS
    ordering = ("-created_at", "-id")
    queryset = AlertRule.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset
        return AlertRule.objects.filter(
            project__owner=self.request.user
        ).select_related("project")


@extend_schema_view(
    get=extend_schema(
        tags=["Alerts"],
        responses={200: AlertRuleSerializer, **_error_responses(403, 404)},
    ),
    patch=extend_schema(
        tags=["Alerts"],
        request=AlertRuleSerializer,
        responses={200: AlertRuleSerializer, **_error_responses(400, 403, 404)},
    ),
    put=extend_schema(
        tags=["Alerts"],
        request=AlertRuleSerializer,
        responses={200: AlertRuleSerializer, **_error_responses(400, 403, 404)},
    ),
    delete=extend_schema(
        tags=["Alerts"],
        responses={204: None, **_error_responses(403, 404)},
    ),
)
class AlertDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AlertRuleSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return AlertRule.objects.filter(
            project__owner=self.request.user
        ).select_related("project")


@extend_schema_view(
    get=extend_schema(
        tags=["Notifications"],
        parameters=[OpenApiParameter("is_read", bool, required=False)],
        responses={
            200: NotificationSerializer(many=True),
            **_error_responses(403),
        },
    )
)
class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [OrderingFilter]
    ordering_fields = NOTIFICATION_ORDERING_FIELDS
    ordering = ("-created_at", "-id")

    def get_queryset(self):
        queryset = Notification.objects.filter(
            user=self.request.user
        ).select_related("project")
        is_read = self.request.query_params.get("is_read")
        if is_read is not None:
            value = is_read.strip().lower()
            if value in {"1", "true", "yes"}:
                queryset = queryset.filter(is_read=True)
            elif value in {"0", "false", "no"}:
                queryset = queryset.filter(is_read=False)
        return queryset


class NotificationReadView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["Notifications"],
        request=None,
        responses={
            200: NotificationSerializer,
            **_error_responses(403, 404),
        },
    )
    def post(self, request, pk):
        try:
            notification = Notification.objects.select_related("project").get(
                pk=pk,
                user=request.user,
            )
        except Notification.DoesNotExist as exc:
            raise NotFound("Notification not found.") from exc
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read"])
        return Response(NotificationSerializer(notification).data)
