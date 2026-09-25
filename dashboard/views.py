from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from analytics.forms import AnalyticsFilterForm
from analytics.services import dashboard_data, error_q, event_time_field, filter_events, owner_events
from monitoring.models import Project


@login_required
def overview(request):
    form = AnalyticsFilterForm(request.GET or None, user=request.user)
    filters = form.cleaned_data if form.is_valid() else {}
    selected_project = filters.get("project")
    data = dashboard_data(request.user, project=selected_project, filters=filters)
    projects = Project.objects.filter(owner=request.user)
    active_project_count = projects.filter(is_active=True).count()
    if selected_project:
        projects = projects.order_by("name")
    else:
        projects = projects.order_by("-updated_at", "name")
    queryset = owner_events(request.user, selected_project)
    queryset = filter_events(queryset, **filters)
    recent_events = queryset.order_by(f"-{event_time_field(queryset)}", "-id")[:8]
    recent_errors = queryset.filter(error_q()).order_by(
        f"-{event_time_field(queryset)}", "-id"
    )[:8]
    return render(
        request,
        "dashboard/overview.html",
        {
            "form": form,
            "filters": filters,
            "data": data,
            "overview": data["overview"],
            "timeline": data["timeline"],
            "event_types": data["event_types"],
            "services": data["services"],
            "environments": data["environments"],
            "status_codes": data["status_codes"],
            "projects": projects,
            "selected_project": selected_project,
            "active_project_count": active_project_count,
            "recent_events": recent_events,
            "recent_errors": recent_errors,
        },
    )


@require_GET
def health(request):
    return JsonResponse({"status": "ok"})


def error_403(request, exception=None):
    return render(
        request,
        "errors/403.html",
        {"status_code": 403},
        status=403,
    )


def error_404(request, exception=None):
    return render(
        request,
        "errors/404.html",
        {"status_code": 404},
        status=404,
    )


def error_500(request):
    return render(
        request,
        "errors/500.html",
        {"status_code": 500},
        status=500,
    )
