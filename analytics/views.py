from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .forms import AnalyticsFilterForm, ErrorMonitoringFilterForm, SlowRequestsFilterForm
from .services import (
    dashboard_data,
    error_q,
    event_time_field,
    filter_events,
    get_event_model,
    group_count,
    owner_events,
    overview as overview_metrics,
    response_time_field,
    timeline,
)


def _clean_filters(form):
    if not form.is_bound:
        return {}
    if form.is_valid():
        return form.cleaned_data
    return {}


def _date_range(filters):
    from datetime import datetime, timedelta, timezone as datetime_timezone

    now = datetime.now(datetime_timezone.utc)
    if filters.get("date_from"):
        start = filters["date_from"]
        start = datetime.combine(start, datetime.min.time(), tzinfo=datetime_timezone.utc)
    else:
        start = now - timedelta(days=7)
    end = filters.get("date_to", now)
    return start, end


def _timeline_context(queryset, filters):
    start, end = _date_range(filters)
    return timeline(queryset, start, end, "hour")


@login_required
def overview(request):
    form = AnalyticsFilterForm(request.GET or None, user=request.user)
    filters = _clean_filters(form)
    project = filters.get("project")
    data = dashboard_data(request.user, project=project, filters=filters)
    return render(
        request,
        "analytics/overview.html",
        {
            "form": form,
            "data": data,
            "overview": data["overview"],
            "timeline": data["timeline"],
            "event_types": data["event_types"],
            "services": data["services"],
            "environments": data["environments"],
        },
    )


@login_required
def error_monitoring(request):
    form = ErrorMonitoringFilterForm(request.GET or None, user=request.user)
    filters = _clean_filters(form)
    queryset = owner_events(request.user, filters.get("project"))
    queryset = filter_events(queryset, **filters)
    queryset = queryset.filter(error_q())
    context = {
        "form": form,
        "overview": overview_metrics(queryset),
        "timeline": _timeline_context(queryset, filters),
        "services": group_count(queryset, "service"),
        "environments": group_count(queryset, "environment"),
        "events": queryset.order_by(f"-{event_time_field(queryset)}")[:100],
    }
    return render(request, "analytics/error_monitoring.html", context)


@login_required
def error_detail(request, event_id):
    event_model = get_event_model()
    event = get_object_or_404(
        event_model.objects.select_related("project"),
        pk=event_id,
        project__owner=request.user,
    )
    return render(request, "analytics/error_detail.html", {"event": event})


@login_required
def slow_requests(request):
    from django.conf import settings

    form = SlowRequestsFilterForm(request.GET or None, user=request.user)
    filters = _clean_filters(form)
    queryset = owner_events(request.user, filters.get("project"))
    queryset = filter_events(queryset, **filters)
    response_field = response_time_field(queryset)
    threshold = getattr(settings, "SLOW_REQUEST_THRESHOLD", None)
    if response_field and threshold is not None:
        queryset = queryset.filter(**{f"{response_field}__gte": threshold})
    context = {
        "form": form,
        "threshold": threshold,
        "overview": overview_metrics(queryset),
        "timeline": _timeline_context(queryset, filters),
        "services": group_count(queryset, "service"),
        "events": queryset.order_by(f"-{event_time_field(queryset)}")[:100],
    }
    return render(request, "analytics/slow_requests.html", context)
