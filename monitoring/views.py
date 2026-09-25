import csv
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView
from django.views.generic.edit import CreateView, DeleteView, UpdateView

from analytics.services import dashboard_data, error_q

from .forms import AlertRuleForm, EventFilterForm, ProjectForm
from .models import ActivityLog, AlertRule, Event, Project


def _log_activity(user, project, action, description=""):
    ActivityLog.objects.create(
        user=user, project=project, action=action, description=description
    )


def _filter_events(queryset, params):
    event_type = params.get("event_type")
    if event_type:
        queryset = queryset.filter(event_type=event_type)
    custom_event_name = params.get("custom_event_name", "").strip()
    if custom_event_name:
        queryset = queryset.filter(custom_event_name__icontains=custom_event_name)
    service = params.get("service", "").strip()
    if service:
        queryset = queryset.filter(service__iexact=service)
    environment = params.get("environment", "").strip()
    if environment:
        queryset = queryset.filter(environment__iexact=environment)
    status_code = params.get("status_code", "").strip()
    if status_code:
        codes = []
        for part in status_code.replace(",", " ").split():
            try:
                codes.append(int(part))
            except ValueError:
                continue
        if codes:
            queryset = queryset.filter(status_code__in=codes)
    date_from = parse_date(params.get("date_from", ""))
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    date_to = parse_date(params.get("date_to", ""))
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)
    return queryset


class ProjectListView(LoginRequiredMixin, ListView):
    model = Project
    template_name = "monitoring/project_list.html"
    context_object_name = "projects"
    paginate_by = 50

    def get_queryset(self):
        return (
            Project.objects.filter(owner=self.request.user)
            .annotate(event_count=Count("events", distinct=True))
            .order_by("-created_at")
        )


class ProjectDashboardView(LoginRequiredMixin, DetailView):
    model = Project
    template_name = "monitoring/project_dashboard.html"
    context_object_name = "project"

    def get_queryset(self):
        return Project.objects.filter(owner=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        project = self.object
        data = dashboard_data(self.request.user, project=project)
        metrics = data["overview"]
        events = project.events.all()
        context["total_events"] = metrics["total"]
        context["error_events"] = metrics["errors"]
        context["success_events"] = metrics["successes"]
        context["avg_response_time"] = metrics["avg_response_time"]
        context["p95_response_time"] = metrics["p95_response_time"]
        context["error_rate"] = metrics["error_rate"]
        context["events_today"] = metrics["today"]
        context["slow_events"] = events.filter(
            response_time__gt=settings.SLOW_REQUEST_THRESHOLD
        ).count()
        context["data"] = data
        context["timeline"] = data["timeline"]
        context["event_types"] = data["event_types"]
        context["services"] = data["services"]
        context["recent_events"] = events.order_by("-created_at", "-id")[:10]
        context["recent_errors"] = (
            events.filter(error_q()).order_by("-created_at", "-id")[:10]
        )
        context["active_alerts"] = project.alert_rules.filter(is_active=True)[:10]
        return context


class ProjectDetailView(LoginRequiredMixin, DetailView):
    model = Project
    template_name = "monitoring/project_detail.html"
    context_object_name = "project"

    def get_queryset(self):
        return Project.objects.filter(owner=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        project = self.object
        context["recent_events"] = project.events.order_by("-created_at")[:10]
        context["active_alerts"] = (
            project.alert_rules.filter(is_active=True).order_by("-updated_at")[:10]
        )
        context["event_count"] = project.events.count()
        generated_key = self.request.session.pop("monitoring_generated_key", None)
        if generated_key:
            context["generated_key"] = generated_key
        return context


class ProjectCreateView(LoginRequiredMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = "monitoring/project_form.html"

    def form_valid(self, form):
        project = form.save(commit=False)
        project.owner = self.request.user
        api_key = Project.generate_api_key()
        project.api_key_hash = Project.hash_api_key(api_key)
        project.api_key_prefix = Project.key_prefix(api_key)
        project.save()
        self.object = project
        self.request.session["monitoring_generated_key"] = api_key
        _log_activity(
            self.request.user,
            project,
            "PROJECT_CREATED",
            f"Created project \"{project.name}\".",
        )
        messages.success(self.request, "Project created.")
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("monitoring:project_detail", args=[self.object.pk])


class ProjectEditView(LoginRequiredMixin, UpdateView):
    model = Project
    form_class = ProjectForm
    template_name = "monitoring/project_form.html"
    context_object_name = "project"

    def get_queryset(self):
        return Project.objects.filter(owner=self.request.user)

    def form_valid(self, form):
        response = super().form_valid(form)
        _log_activity(
            self.request.user,
            self.object,
            "PROJECT_UPDATED",
            f"Updated project \"{self.object.name}\".",
        )
        messages.success(self.request, "Project updated.")
        return response

    def get_success_url(self):
        return reverse("monitoring:project_detail", args=[self.object.pk])


class ProjectDeleteView(LoginRequiredMixin, DeleteView):
    model = Project
    template_name = "monitoring/project_confirm_delete.html"
    context_object_name = "project"
    http_method_names = ["post"]

    def get_queryset(self):
        return Project.objects.filter(owner=self.request.user)

    def get_success_url(self):
        return reverse("monitoring:project_list")

    def form_valid(self, form):
        project = self.object
        response = super().form_valid(form)
        _log_activity(
            self.request.user,
            None,
            "PROJECT_DELETED",
            f"Deleted project \"{project.name}\".",
        )
        messages.success(self.request, "Project deleted.")
        return response


@login_required
@require_POST
def project_regenerate_key(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    api_key = project.rotate_api_key()
    _log_activity(
        request.user,
        project,
        "KEY_REGENERATED",
        f"Regenerated API key for project \"{project.name}\".",
    )
    messages.success(request, "New API key generated. Copy it now.")
    return render(
        request,
        "monitoring/project_key.html",
        {"project": project, "api_key": api_key},
    )


class EventListView(LoginRequiredMixin, ListView):
    model = Event
    template_name = "monitoring/event_list.html"
    context_object_name = "events"
    paginate_by = 50

    def get_queryset(self):
        self.project = get_object_or_404(
            Project, pk=self.kwargs["pk"], owner=self.request.user
        )
        queryset = _filter_events(
            self.project.events.select_related("project"), self.request.GET
        )
        return queryset.order_by("-created_at", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["project"] = self.project
        context["filter_form"] = EventFilterForm(self.request.GET)
        return context


class EventDetailView(LoginRequiredMixin, DetailView):
    model = Event
    template_name = "monitoring/event_detail.html"
    context_object_name = "event"

    def get_object(self, queryset=None):
        return get_object_or_404(
            Event,
            pk=self.kwargs["event_pk"],
            project__pk=self.kwargs["pk"],
            project__owner=self.request.user,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["project"] = self.object.project
        return context


@login_required
def event_export(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    queryset = _filter_events(project.events.all(), request.GET).order_by(
        "-created_at", "-id"
    )
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="events-{project.id}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "id",
            "event_type",
            "custom_event_name",
            "message",
            "service",
            "environment",
            "status_code",
            "response_time",
            "ip_address",
            "metadata",
            "created_at",
        ]
    )
    for event in queryset.iterator():
        writer.writerow(
            [
                event.id,
                event.event_type,
                event.custom_event_name,
                event.message,
                event.service,
                event.environment,
                event.status_code,
                event.response_time,
                event.ip_address,
                json.dumps(event.metadata),
                event.created_at.isoformat(),
            ]
        )
    return response


class AlertRuleListView(LoginRequiredMixin, ListView):
    model = AlertRule
    template_name = "monitoring/alert_list.html"
    context_object_name = "alert_rules"

    def get_queryset(self):
        self.project = get_object_or_404(
            Project, pk=self.kwargs["pk"], owner=self.request.user
        )
        return self.project.alert_rules.order_by("-created_at", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["project"] = self.project
        return context


class AlertRuleCreateView(LoginRequiredMixin, CreateView):
    model = AlertRule
    form_class = AlertRuleForm
    template_name = "monitoring/alert_form.html"

    def get(self, request, *args, **kwargs):
        self.project = get_object_or_404(
            Project, pk=self.kwargs["pk"], owner=self.request.user
        )
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        self.project = get_object_or_404(
            Project, pk=self.kwargs["pk"], owner=self.request.user
        )
        alert_rule = form.save(commit=False)
        alert_rule.project = self.project
        alert_rule.save()
        self.object = alert_rule
        _log_activity(
            self.request.user,
            self.project,
            "ALERT_CREATED",
            f"Created alert rule \"{alert_rule.name}\".",
        )
        messages.success(self.request, "Alert rule created.")
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if hasattr(self, "project"):
            context["project"] = self.project
        return context

    def get_success_url(self):
        return reverse("monitoring:alert_list", args=[self.kwargs["pk"]])


@login_required
@require_POST
def alert_toggle(request, pk, alert_pk):
    alert_rule = get_object_or_404(
        AlertRule,
        pk=alert_pk,
        project__pk=pk,
        project__owner=request.user,
    )
    alert_rule.is_active = not alert_rule.is_active
    alert_rule.save(update_fields=["is_active", "updated_at"])
    _log_activity(
        request.user,
        alert_rule.project,
        "ALERT_TOGGLED",
        f"{'Enabled' if alert_rule.is_active else 'Disabled'} alert rule "
        f"\"{alert_rule.name}\".",
    )
    messages.success(
        request,
        "Alert rule enabled." if alert_rule.is_active else "Alert rule disabled.",
    )
    return redirect("monitoring:alert_list", pk=pk)


class ActivityLogListView(LoginRequiredMixin, ListView):
    model = ActivityLog
    template_name = "monitoring/activity_list.html"
    context_object_name = "activity_logs"
    paginate_by = 50

    def get_queryset(self):
        return (
            ActivityLog.objects.filter(user=self.request.user)
            .select_related("user", "project")
            .order_by("-created_at", "-id")
        )