from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date as Date
from datetime import datetime, time, timedelta, timezone as datetime_timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDay, TruncHour, TruncMinute, TruncMonth, TruncWeek
from django.utils import timezone


ERROR_EVENT_TYPES = ("APPLICATION_ERROR", "DATABASE_ERROR")
EVENT_TIME_FIELDS = ("timestamp", "occurred_at", "created_at", "created")
RESPONSE_TIME_FIELDS = (
    "response_time",
    "response_time_ms",
    "duration",
    "duration_ms",
    "latency",
    "latency_ms",
)
SEARCH_FIELDS = (
    "event_type",
    "custom_event_name",
    "service",
    "environment",
    "path",
    "url",
    "request_path",
    "message",
    "error_message",
    "traceback",
    "request_id",
    "user_id",
    "ip_address",
    "user_agent",
)
GROUP_COUNT_FIELDS = frozenset(
    {"project", "event_type", "service", "environment", "status_code"}
)
FILTER_FIELDS = frozenset(
    {
        "project",
        "date_from",
        "date_to",
        "event_type",
        "service",
        "services",
        "environment",
        "status_code",
        "slow",
        "search",
    }
)
CACHE_VERSION_KEY = "analytics:cache-version"
OWNER_CACHE_VERSION_PREFIX = "analytics:version:owner:"
PROJECT_CACHE_VERSION_PREFIX = "analytics:version:project:"

Project = None
Event = None


def get_project_model():
    global Project
    if Project is not None:
        return Project
    Project = apps.get_model("monitoring", "Project")
    return Project


def get_event_model():
    global Event
    if Event is not None:
        return Event
    for model_name in ("Event", "EventLog", "EventRecord"):
        try:
            Event = apps.get_model("monitoring", model_name)
        except LookupError:
            continue
        return Event
    raise LookupError("The monitoring event model could not be found")


def _model_has_field(model, field_name):
    if model is None:
        return True
    try:
        model._meta.get_field(field_name)
    except (AttributeError, FieldDoesNotExist):
        return False
    return True


def _field_name(queryset, candidates, default=None):
    model = getattr(queryset, "model", None)
    for candidate in candidates:
        if _model_has_field(model, candidate):
            return candidate
    return default


def event_time_field(queryset):
    return _field_name(queryset, EVENT_TIME_FIELDS, "timestamp")


def response_time_field(queryset):
    return _field_name(queryset, RESPONSE_TIME_FIELDS)


def _error_q_for_model(model):
    query = Q(status_code__gte=400)
    if _model_has_field(model, "event_type"):
        query |= Q(event_type__in=ERROR_EVENT_TYPES)
    return query


def _success_q_for_model(model):
    query = Q(status_code__gte=200) & Q(status_code__lt=400)
    if _model_has_field(model, "event_type"):
        query &= ~Q(event_type__in=ERROR_EVENT_TYPES)
    return query


def error_q() -> Q:
    return Q(status_code__gte=400) | Q(event_type__in=ERROR_EVENT_TYPES)


def success_q() -> Q:
    return Q(status_code__gte=200) & Q(status_code__lt=400) & ~Q(
        event_type__in=ERROR_EVENT_TYPES
    )


def parse_iso_date(value: Date | datetime | str) -> Date:
    if isinstance(value, datetime):
        parsed = value
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, datetime_timezone.utc)
        else:
            parsed = parsed.astimezone(datetime_timezone.utc)
        return parsed.date()
    if isinstance(value, Date):
        return value
    if not isinstance(value, str):
        raise ValueError("Date must be an ISO-8601 date")
    text = value.strip()
    if not text:
        raise ValueError("Date must not be empty")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return Date.fromisoformat(text)
        normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
        parsed = datetime.fromisoformat(normalized)
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, datetime_timezone.utc)
        else:
            parsed = parsed.astimezone(datetime_timezone.utc)
        return parsed.date()
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Date must be an ISO-8601 date") from exc


def validate_iso_date(value: Any) -> bool:
    try:
        parse_iso_date(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return True


def parse_date(value: Date | datetime | str) -> Date:
    return parse_iso_date(value)


def validate_date(value: Any) -> bool:
    return validate_iso_date(value)


def _utc_start(day: Date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=datetime_timezone.utc)


def _coerce_datetime(value: Date | datetime | str) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        parsed = value
        date_only = False
    elif isinstance(value, Date):
        parsed = datetime.combine(value, time.min)
        date_only = True
    elif isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            parsed = datetime.combine(parse_iso_date(text), time.min)
            date_only = True
        else:
            normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
            try:
                parsed = datetime.fromisoformat(normalized)
            except (TypeError, ValueError) as exc:
                raise ValueError("Datetime must be ISO-8601") from exc
            date_only = False
    else:
        raise ValueError("Datetime must be an ISO-8601 value")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, datetime_timezone.utc)
    else:
        parsed = parsed.astimezone(datetime_timezone.utc)
    return parsed, date_only


def _first_value(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _is_model_instance(value):
    return hasattr(value, "_meta") and hasattr(value, "pk")


def _project_filter(queryset, project):
    if _is_model_instance(project):
        return queryset.filter(project=project)
    if isinstance(project, str) and not project.isdigit():
        project_model = get_project_model()
        conditions = Q(project__name=project)
        if _model_has_field(project_model, "slug"):
            conditions |= Q(project__slug=project)
        return queryset.filter(conditions)
    return queryset.filter(project_id=project)


def _search_filter(queryset, search):
    model = getattr(queryset, "model", None)
    fields = [field for field in SEARCH_FIELDS if _model_has_field(model, field)]
    if not fields:
        return queryset.none()
    condition = Q()
    for field in fields:
        condition |= Q(**{f"{field}__icontains": search})
    return queryset.filter(condition)


def _date_boundary(value, end=False):
    if value in (None, ""):
        return None, False
    if isinstance(value, datetime):
        return value, False
    if isinstance(value, Date):
        day_start = _utc_start(value)
        return day_start + timedelta(days=1) if end else day_start, True
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        day = parse_iso_date(text)
        day_start = _utc_start(day)
        return day_start + timedelta(days=1) if end else day_start, True
    parsed, _ = _coerce_datetime(text)
    return parsed, False


def filter_events(
    queryset,
    project=None,
    date_from=None,
    date_to=None,
    event_type=None,
    service=None,
    services=None,
    environment=None,
    status_code=None,
    slow=None,
    search=None,
):
    if project is not None:
        queryset = _project_filter(queryset, project)
    time_field = event_time_field(queryset)
    start, _ = _date_boundary(date_from)
    end, end_is_date = _date_boundary(date_to, end=True)
    if start is not None and end is not None and start > end:
        raise ValueError("date_from must not be after date_to")
    if start is not None:
        queryset = queryset.filter(**{f"{time_field}__gte": start})
    if end is not None:
        lookup = "lt" if end_is_date else "lte"
        queryset = queryset.filter(**{f"{time_field}__{lookup}": end})
    if event_type not in (None, ""):
        queryset = queryset.filter(event_type=event_type)
    if service not in (None, "") and services not in (None, "", []):
        if isinstance(services, str):
            services = [services]
        queryset = queryset.filter(service__in=[service, *list(services)])
    elif service not in (None, ""):
        queryset = queryset.filter(service=service)
    elif services not in (None, "", []):
        if isinstance(services, str):
            services = [services]
        queryset = queryset.filter(service__in=list(services))
    if environment not in (None, ""):
        queryset = queryset.filter(environment=environment)
    if status_code not in (None, ""):
        queryset = queryset.filter(status_code=int(status_code))
    if slow:
        threshold = getattr(settings, "SLOW_REQUEST_THRESHOLD", None)
        if threshold is not None:
            queryset = queryset.filter(response_time__gte=threshold)
    if search not in (None, ""):
        queryset = _search_filter(queryset, str(search).strip())
    return queryset


def _number(value):
    if isinstance(value, timedelta):
        return value.total_seconds() * 1000
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _response_values(queryset):
    field_name = response_time_field(queryset)
    if not field_name:
        return []
    values = (
        queryset.exclude(**{f"{field_name}__isnull": True})
        .order_by(field_name)
        .values_list(field_name, flat=True)
    )
    result = []
    for value in values:
        if value is None:
            continue
        try:
            number = _number(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(number):
            result.append(number)
    return result


def response_percentile(queryset, p):
    try:
        percentile = float(p)
    except (TypeError, ValueError) as exc:
        raise ValueError("Percentile must be a number between 0 and 100") from exc
    if not math.isfinite(percentile):
        raise ValueError("Percentile must be a number between 0 and 100")
    if 0 <= percentile <= 1:
        fraction = percentile
    elif 0 <= percentile <= 100:
        fraction = percentile / 100
    else:
        raise ValueError("Percentile must be between 0 and 1 or 0 and 100")
    values = _response_values(queryset)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(values) - 1)
    weight = position - lower_index
    return values[lower_index] + (values[upper_index] - values[lower_index]) * weight


def _response_stats(queryset):
    values = _response_values(queryset)
    if not values:
        return {
            "avg_response_time": None,
            "min_response_time": None,
            "max_response_time": None,
            "p50_response_time": None,
            "p95_response_time": None,
            "p99_response_time": None,
        }
    return {
        "avg_response_time": sum(values) / len(values),
        "min_response_time": min(values),
        "max_response_time": max(values),
        "p50_response_time": response_percentile(queryset, 0.50),
        "p95_response_time": response_percentile(queryset, 0.95),
        "p99_response_time": response_percentile(queryset, 0.99),
    }


def overview(queryset) -> dict[str, Any]:
    now = timezone.now().astimezone(datetime_timezone.utc)
    total = queryset.count()
    errors = queryset.filter(_error_q_for_model(getattr(queryset, "model", None))).count()
    successes = queryset.filter(
        _success_q_for_model(getattr(queryset, "model", None))
    ).count()
    time_field = event_time_field(queryset)
    today = queryset.filter(
        **{f"{time_field}__gte": _utc_start(now.date())}
    ).count()
    week = queryset.filter(
        **{f"{time_field}__gte": now - timedelta(days=7)}
    ).count()
    month = queryset.filter(
        **{f"{time_field}__gte": now - timedelta(days=30)}
    ).count()
    error_rate = (errors / total * 100) if total else 0.0
    return {
        "total": int(total),
        "today": int(today),
        "week": int(week),
        "month": int(month),
        "errors": int(errors),
        "successes": int(successes),
        "error_rate": error_rate,
        **_response_stats(queryset),
    }


def group_count(queryset, field):
    if field not in GROUP_COUNT_FIELDS:
        allowed = ", ".join(sorted(GROUP_COUNT_FIELDS))
        raise ValueError(f"Unsupported grouping field. Choose one of: {allowed}")
    value_field = "project_id" if field == "project" else field
    return (
        queryset.values(value_field)
        .annotate(count=Count("id"))
        .order_by("-count", value_field)
    )


def timeline(queryset, start, end, grain):
    normalized_grain = {
        "hourly": "hour",
        "daily": "day",
        "weekly": "week",
        "monthly": "month",
    }.get(grain, grain)
    truncators = {
        "minute": TruncMinute,
        "hour": TruncHour,
        "day": TruncDay,
        "week": TruncWeek,
        "month": TruncMonth,
    }
    if normalized_grain not in truncators:
        raise ValueError("Unsupported timeline grain")
    start_value, _ = _coerce_datetime(start)
    end_value, end_is_date = _coerce_datetime(end)
    if start_value > end_value:
        raise ValueError("Timeline start must not be after end")
    time_field = event_time_field(queryset)
    if end_is_date:
        end_exclusive = end_value + timedelta(days=1)
        queryset = queryset.filter(
            **{f"{time_field}__gte": start_value}
        ).filter(**{f"{time_field}__lt": end_exclusive})
    else:
        queryset = queryset.filter(
            **{f"{time_field}__gte": start_value}
        ).filter(**{f"{time_field}__lte": end_value})
    truncator = truncators[normalized_grain]
    annotations = {
        "bucket": truncator(time_field, tzinfo=datetime_timezone.utc),
        "total": Count("id"),
        "errors": Count("id", filter=_error_q_for_model(getattr(queryset, "model", None))),
        "successes": Count(
            "id", filter=_success_q_for_model(getattr(queryset, "model", None))
        ),
    }
    response_field = response_time_field(queryset)
    if response_field:
        annotations["avg_response_time"] = Avg(response_field)
    return queryset.annotate(**annotations).values(*annotations).order_by("bucket")


def _read_version(key):
    current = cache.get(key)
    if current is None:
        cache.add(key, 1, timeout=None)
        current = cache.get(key, 1)
    try:
        return max(1, int(current))
    except (TypeError, ValueError):
        cache.set(key, 1, timeout=None)
        return 1


def _increment_version(key):
    try:
        if cache.add(key, 1, timeout=None):
            return 1
        return max(1, int(cache.incr(key)))
    except (NotImplementedError, TypeError, ValueError):
        updated = _read_version(key) + 1
        cache.set(key, updated, timeout=None)
        return updated


def _scope_id(value, owner_scope=False):
    if value is None:
        return None
    if owner_scope:
        owner_id = getattr(value, "owner_id", None)
        if owner_id is not None:
            return owner_id
        owner = getattr(value, "owner", None)
        if owner is not None and getattr(owner, "pk", None) is not None:
            return owner.pk
        return getattr(value, "pk", value)
    return getattr(value, "pk", value)


def get_cache_version(owner=None, project=None, *, owner_id=None, project_id=None) -> int:
    owner_id = owner_id if owner_id is not None else _scope_id(owner, owner_scope=True)
    project_id = project_id if project_id is not None else _scope_id(project)
    if project_id is not None:
        return _read_version(f"{PROJECT_CACHE_VERSION_PREFIX}{project_id}")
    if owner_id is not None:
        return _read_version(f"{OWNER_CACHE_VERSION_PREFIX}{owner_id}")
    return _read_version(CACHE_VERSION_KEY)


def increment_cache_version(
    owner=None,
    project=None,
    *,
    owner_id=None,
    project_id=None,
) -> int:
    owner_id = owner_id if owner_id is not None else _scope_id(owner, owner_scope=True)
    project_id = project_id if project_id is not None else _scope_id(project)
    if owner_id is None and project is not None:
        owner_id = getattr(project, "owner_id", None)
    version = _increment_version(CACHE_VERSION_KEY)
    if owner_id is not None:
        _increment_version(f"{OWNER_CACHE_VERSION_PREFIX}{owner_id}")
    if project_id is not None:
        _increment_version(f"{PROJECT_CACHE_VERSION_PREFIX}{project_id}")
    return version


def bump_analytics_version(project_id=None, owner_id=None) -> int:
    return increment_cache_version(project_id=project_id, owner_id=owner_id)


def _dashboard_version(owner, project=None):
    versions = [str(get_cache_version())]
    owner_id = _scope_id(owner, owner_scope=True)
    if owner_id is not None:
        versions.append(str(_read_version(f"{OWNER_CACHE_VERSION_PREFIX}{owner_id}")))
    project_id = _scope_id(project)
    if project_id is not None:
        versions.append(str(_read_version(f"{PROJECT_CACHE_VERSION_PREFIX}{project_id}")))
    return "-".join(versions)


def _json_safe(value):
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = value.replace(tzinfo=datetime_timezone.utc)
        else:
            value = value.astimezone(datetime_timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Date):
        return value.isoformat()
    if isinstance(value, Decimal):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if _is_model_instance(value):
        return _json_safe(value.pk)
    return value


def _project_owner_id(project):
    owner_id = getattr(project, "owner_id", None)
    if owner_id is not None:
        return owner_id
    owner = getattr(project, "owner", None)
    return getattr(owner, "pk", None)


def _resolve_project(owner, project):
    if getattr(owner, "is_authenticated", True) is False or getattr(owner, "pk", None) is None:
        raise PermissionDenied("An authenticated owner is required")
    project_model = get_project_model()
    if _is_model_instance(project):
        if _project_owner_id(project) != owner.pk:
            raise PermissionDenied("The project is not owned by this user")
        return project
    project_qs = project_model.objects.filter(owner_id=owner.pk)
    if isinstance(project, str) and not project.isdigit():
        conditions = Q(name=project)
        if _model_has_field(project_model, "slug"):
            conditions |= Q(slug=project)
        try:
            return project_qs.get(conditions)
        except project_model.DoesNotExist as exc:
            raise PermissionDenied("The project is not owned by this user") from exc
    try:
        return project_qs.get(pk=project)
    except (project_model.DoesNotExist, ValueError, TypeError) as exc:
        raise PermissionDenied("The project is not owned by this user") from exc


def owner_events(owner, project=None):
    if getattr(owner, "is_authenticated", True) is False or getattr(owner, "pk", None) is None:
        raise PermissionDenied("An authenticated owner is required")
    project_object = _resolve_project(owner, project) if project is not None else None
    event_model = get_event_model()
    queryset = event_model.objects.all()
    if project_object is not None:
        queryset = queryset.filter(project_id=project_object.pk)
    return queryset.filter(project__owner_id=owner.pk)


def _normalise_filters(filters):
    if not filters:
        return {}
    normalised = {}
    for field in FILTER_FIELDS:
        value = filters.get(field)
        if field == "services":
            if isinstance(value, str):
                value = [item.strip() for item in value.split(",") if item.strip()]
            elif value is not None:
                value = list(value)
        else:
            value = _first_value(value)
        if value not in (None, "", []):
            normalised[field] = value
    return normalised


def _timeline_rows(queryset, start, end, grain):
    rows = []
    for row in timeline(queryset, start, end, grain):
        item = {
            "timestamp": _json_safe(row.get("bucket")),
            "total": int(row.get("total", 0)),
            "errors": int(row.get("errors", 0)),
            "successes": int(row.get("successes", 0)),
            "avg_response_time": _json_safe(row.get("avg_response_time")),
        }
        rows.append(item)
    return rows


def _group_rows(queryset, field):
    rows = []
    for row in group_count(queryset, field):
        value = row.get("project_id") if field == "project" else row.get(field)
        rows.append({"value": _json_safe(value), "count": int(row.get("count", 0))})
    return rows


def _dashboard_cache_key(owner, project, filters, version):
    payload = {"filters": filters}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()
    project_part = "all" if project is None else str(project.pk)
    return f"analytics:dashboard:{owner.pk}:{project_part}:{version}:{digest}"


def dashboard_data(owner, project=None, filters=None, cache_ttl=None) -> dict[str, Any]:
    project_value = project
    normalised_filters = _normalise_filters(filters)
    filter_project = normalised_filters.pop("project", None)
    if project_value is None:
        project_value = filter_project
    project_object = _resolve_project(owner, project_value) if project_value is not None else None
    queryset = owner_events(owner, project_object)
    queryset = filter_events(queryset, **normalised_filters)
    ttl = getattr(settings, "ANALYTICS_CACHE_TTL", 30) if cache_ttl is None else cache_ttl
    try:
        ttl = int(ttl)
    except (TypeError, ValueError):
        ttl = 0
    version = _dashboard_version(owner, project_object) if ttl > 0 else "uncached"
    cache_key = _dashboard_cache_key(
        owner, project_object, normalised_filters, version
    ) if ttl > 0 else None
    if cache_key is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            return _json_safe(cached)
    grain = normalised_filters.pop("grain", "hour")
    now = timezone.now().astimezone(datetime_timezone.utc)
    if "date_from" in normalised_filters:
        start, _ = _date_boundary(normalised_filters["date_from"])
    else:
        start = now - timedelta(days=7)
    end = normalised_filters.get("date_to", now)
    result = {
        "overview": overview(queryset),
        "timeline": _timeline_rows(queryset, start, end, grain),
        "event_types": _group_rows(queryset, "event_type"),
        "services": _group_rows(queryset, "service"),
        "environments": _group_rows(queryset, "environment"),
        "status_codes": _group_rows(queryset, "status_code"),
    }
    if project_object is not None:
        result["project"] = {
            "id": _json_safe(project_object.pk),
            "name": str(project_object),
        }
    else:
        result["project"] = None
    result["filters"] = {
        key: _json_safe(value)
        for key, value in normalised_filters.items()
        if key != "project"
    }
    result = _json_safe(result)
    if cache_key is not None:
        cache.set(cache_key, result, timeout=ttl)
    return result


def summarize_project(project, date):
    from .models import DailyAnalyticsSummary

    day = parse_iso_date(date)
    event_model = get_event_model()
    start = _utc_start(day)
    end = start + timedelta(days=1)
    queryset = event_model.objects.filter(
        project_id=project.pk,
        **{f"{event_time_field(event_model.objects.all())}__gte": start},
    ).filter(**{f"{event_time_field(event_model.objects.all())}__lt": end})
    total = queryset.count()
    errors = queryset.filter(_error_q_for_model(event_model)).count()
    successes = queryset.filter(_success_q_for_model(event_model)).count()
    stats = _response_stats(queryset)
    return DailyAnalyticsSummary.objects.update_or_create(
        project=project,
        date=day,
        defaults={
            "total_events": total,
            "error_events": errors,
            "success_events": successes,
            "error_rate": (errors / total * 100) if total else 0.0,
            **stats,
        },
    )[0]
