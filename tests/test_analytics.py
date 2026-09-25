from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from analytics.forms import AnalyticsFilterForm
from analytics.models import DailyAnalyticsSummary
from analytics.services import (
    dashboard_data,
    error_q,
    filter_events,
    group_count,
    owner_events,
    overview,
    parse_iso_date,
    response_percentile,
    success_q,
    summarize_project,
    validate_iso_date,
)
from monitoring.models import Event
from tests.factories import create_event, create_project, create_user, hours_ago


class DateParsingTests(TestCase):
    def test_parses_date_only_and_datetime_strings(self):
        self.assertEqual(parse_iso_date("2024-05-01"), date(2024, 5, 1))
        self.assertEqual(
            parse_iso_date("2024-05-01T12:30:00Z"),
            date(2024, 5, 1),
        )
        self.assertTrue(validate_iso_date("2024-05-01"))
        self.assertFalse(validate_iso_date("not-a-date"))
        self.assertFalse(validate_iso_date(""))

    def test_rejects_reversed_ranges(self):
        with self.assertRaises(ValueError):
            filter_events(
                Event.objects.all(), date_from="2024-05-10", date_to="2024-05-01"
            )


class OverviewTests(TestCase):
    def setUp(self):
        self.owner = create_user("analyticsowner")
        self.project = create_project(self.owner)
        cache.clear()

    def _seed(self):
        create_event(self.project, status_code=200, response_time=100)
        create_event(self.project, status_code=201, response_time=200)
        create_event(self.project, status_code=404, response_time=50)
        create_event(
            self.project,
            event_type=Event.EventType.DATABASE_ERROR,
            status_code=500,
            response_time=400,
        )

    def test_overview_counts_errors_and_successes(self):
        self._seed()
        stats = overview(owner_events(self.owner))
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["errors"], 2)
        self.assertEqual(stats["successes"], 2)
        self.assertAlmostEqual(stats["error_rate"], 50.0)
        self.assertAlmostEqual(stats["avg_response_time"], 187.5)
        self.assertEqual(stats["min_response_time"], 50)
        self.assertEqual(stats["max_response_time"], 400)

    def test_empty_overview_has_no_response_stats(self):
        stats = overview(owner_events(self.owner))
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["error_rate"], 0.0)
        self.assertIsNone(stats["avg_response_time"])

    def test_error_and_success_query_sets(self):
        self._seed()
        events = owner_events(self.owner)
        self.assertEqual(events.filter(error_q()).count(), 2)
        self.assertEqual(events.filter(success_q()).count(), 2)

    def test_percentiles(self):
        for value in (10, 20, 30, 40, 50):
            create_event(self.project, response_time=value)
        events = owner_events(self.owner)
        self.assertAlmostEqual(response_percentile(events, 0.5), 30.0)
        self.assertAlmostEqual(response_percentile(events, 0.95), 48.0)
        self.assertAlmostEqual(response_percentile(events, 95), 48.0)
        self.assertIsNone(response_percentile(owner_events(create_user("empty")), 0.5))

    def test_group_count(self):
        create_event(self.project, service="api", event_type=Event.EventType.API_REQUEST)
        create_event(self.project, service="api", event_type=Event.EventType.ORDER)
        create_event(self.project, service="worker", event_type=Event.EventType.API_REQUEST)
        rows = list(group_count(owner_events(self.owner), "service"))
        self.assertEqual(rows[0]["service"], "api")
        self.assertEqual(rows[0]["count"], 2)
        with self.assertRaises(ValueError):
            group_count(owner_events(self.owner), "not_a_field")


class FilterTests(TestCase):
    def setUp(self):
        self.owner = create_user("filterowner")
        self.project = create_project(self.owner)
        self.other = create_project(self.owner, "Other project")
        create_event(self.project, service="api", environment="production", status_code=200)
        create_event(self.project, service="worker", environment="staging", status_code=500)
        create_event(self.other, service="api", environment="production", status_code=404)

    def test_filter_by_project_object(self):
        events = filter_events(owner_events(self.owner), project=self.project)
        self.assertEqual(events.count(), 2)

    def test_filter_by_service_and_environment(self):
        events = owner_events(self.owner)
        self.assertEqual(filter_events(events, service="api").count(), 2)
        self.assertEqual(filter_events(events, environment="staging").count(), 1)
        self.assertEqual(filter_events(events, service="api", environment="staging").count(), 0)

    def test_filter_by_status_code_and_slow(self):
        events = owner_events(self.owner)
        self.assertEqual(filter_events(events, status_code=500).count(), 1)
        self.assertEqual(filter_events(events, slow=True).count(), 0)

    def test_filter_by_date_range(self):
        events = owner_events(self.owner)
        today = date.today()
        self.assertEqual(
            filter_events(events, date_from=today, date_to=today).count(), 3
        )
        self.assertEqual(
            filter_events(events, date_from=today - timedelta(days=1), date_to=today).count(),
            3,
        )

    def test_search_filter(self):
        events = owner_events(self.owner)
        self.assertEqual(filter_events(events, search="worker").count(), 1)
        self.assertEqual(filter_events(events, search="zzz-nothing").count(), 0)


class OwnerScopingTests(TestCase):
    def setUp(self):
        self.owner = create_user("scopeowner")
        self.stranger = create_user("scopestranger")
        self.project = create_project(self.owner)
        create_event(self.project)

    def test_owner_events_filters_to_owned_projects(self):
        self.assertEqual(owner_events(self.owner).count(), 1)
        self.assertEqual(owner_events(self.stranger).count(), 0)

    def test_dashboard_data_rejects_other_users_project(self):
        with self.assertRaises(PermissionDenied):
            dashboard_data(self.stranger, project=self.project)

    def test_dashboard_data_rejects_anonymous_owner(self):
        from django.contrib.auth.models import AnonymousUser

        with self.assertRaises(PermissionDenied):
            owner_events(AnonymousUser())


class DashboardDataTests(TestCase):
    def setUp(self):
        self.owner = create_user("dashdata")
        self.project = create_project(self.owner, "Dash project")
        cache.clear()
        create_event(self.project, status_code=200, response_time=100, created_at=hours_ago(1))
        create_event(self.project, status_code=500, response_time=900, created_at=hours_ago(2))
        create_event(
            self.project, status_code=404, service="worker", created_at=hours_ago(3)
        )

    def test_dashboard_data_structure(self):
        data = dashboard_data(self.owner)
        self.assertIn("overview", data)
        self.assertIn("timeline", data)
        self.assertEqual(data["overview"]["total"], 3)
        self.assertEqual(data["overview"]["errors"], 2)
        self.assertEqual(data["overview"]["successes"], 1)
        self.assertEqual(data["project"], None)
        self.assertTrue(data["timeline"])

    def test_dashboard_data_json_safe(self):
        import json

        data = dashboard_data(self.owner, project=self.project)
        json.dumps(data)  # should not raise
        self.assertEqual(data["project"]["id"], self.project.pk)

    def test_dashboard_data_is_cached_and_invalidated(self):
        first = dashboard_data(self.owner, project=self.project)
        self.assertEqual(first["overview"]["total"], 3)
        create_event(self.project, status_code=200, response_time=50)
        from analytics.services import increment_cache_version

        increment_cache_version(project=self.project)
        refreshed = dashboard_data(self.owner, project=self.project)
        self.assertEqual(refreshed["overview"]["total"], 4)


class DailySummaryTests(TestCase):
    def setUp(self):
        self.owner = create_user("summaryowner")
        self.project = create_project(self.owner, "Summary project")
        cache.clear()
        now = timezone.now()
        create_event(self.project, status_code=200, response_time=100, created_at=now)
        create_event(self.project, status_code=500, response_time=300, created_at=now)
        create_event(self.project, status_code=200, response_time=200, created_at=now)

    def test_summarize_project_creates_daily_summary(self):
        summary = summarize_project(self.project, date.today())
        self.assertIsInstance(summary, DailyAnalyticsSummary)
        self.assertEqual(summary.total_events, 3)
        self.assertEqual(summary.error_events, 1)
        self.assertEqual(summary.success_events, 2)
        self.assertAlmostEqual(float(summary.error_rate), 33.3333, places=3)

    def test_summarize_project_is_idempotent(self):
        summarize_project(self.project, date.today())
        summary = summarize_project(self.project, date.today())
        self.assertEqual(DailyAnalyticsSummary.objects.filter(project=self.project).count(), 1)
        self.assertEqual(summary.total_events, 3)


class AnalyticsViewTests(TestCase):
    def setUp(self):
        self.owner = create_user("analyticsview")
        self.stranger = create_user("analyticsstranger")
        self.project = create_project(self.owner, "Analytics project")
        cache.clear()
        create_event(self.project, status_code=200, response_time=100)
        create_event(self.project, status_code=500, response_time=900)

    def test_overview_requires_login(self):
        response = self.client.get(reverse("analytics:overview"))
        self.assertEqual(response.status_code, 302)

    def test_overview_renders_for_owner(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("analytics:overview"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["overview"]["total"], 2)

    def test_error_monitoring_shows_only_errors(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("analytics:error_monitoring"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["overview"]["total"], 1)
        self.assertEqual(response.context["overview"]["errors"], 1)

    def test_slow_requests_respects_threshold(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("analytics:slow_requests"))
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.context["overview"]["total"], 0)

    def test_project_filter_form_is_scoped_to_owner(self):
        form = AnalyticsFilterForm(user=self.owner)
        self.assertEqual(
            list(form.fields["project"].queryset), [self.owner.monitoring_projects.get()]
        )
        stranger_form = AnalyticsFilterForm(user=self.stranger)
        self.assertEqual(list(stranger_form.fields["project"].queryset), [])

    def test_project_filter_form_rejects_inverted_dates(self):
        form = AnalyticsFilterForm(
            data={"date_from": "2024-05-10", "date_to": "2024-05-01"}, user=self.owner
        )
        self.assertFalse(form.is_valid())
        self.assertTrue(form.errors)

    def test_error_detail_is_owner_scoped(self):
        event = self.project.events.first()
        self.client.force_login(self.stranger)
        response = self.client.get(
            reverse("analytics:error_detail", args=[event.pk])
        )
        self.assertEqual(response.status_code, 404)
