import csv
import io
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from monitoring.models import AlertRule, AlertTrigger, Event
from monitoring.tasks import (
    cleanup_old_events,
    detect_abnormal_error_spikes,
    process_event,
)
from notifications.models import Notification
from tests.factories import (
    create_alert_rule,
    create_event,
    create_notification,
    create_project,
    create_user,
    hours_ago,
)


class ProjectViewTests(TestCase):
    def setUp(self):
        self.owner = create_user("viewowner")
        self.stranger = create_user("viewstranger")
        self.project = create_project(self.owner, "Owner project")
        self.other_project = create_project(self.stranger, "Stranger project")

    def test_project_list_only_shows_owned_projects(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("monitoring:project_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Owner project")
        self.assertNotContains(response, "Stranger project")

    def test_project_detail_is_hidden_from_non_owners(self):
        self.client.force_login(self.stranger)
        response = self.client.get(
            reverse("monitoring:project_detail", args=[self.project.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_project_detail_shows_api_key_once_after_creation(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("monitoring:project_create"),
            {"name": "Fresh project", "description": "Created in a test"},
        )
        self.assertEqual(response.status_code, 302)
        project = self.owner.monitoring_projects.get(name="Fresh project")
        self.assertTrue(project.api_key_hash)
        self.assertNotIn(project.api_key_hash, response.get("Location", ""))

        detail = self.client.get(
            reverse("monitoring:project_detail", args=[project.pk])
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Your API key is ready")

        second_visit = self.client.get(
            reverse("monitoring:project_detail", args=[project.pk])
        )
        self.assertNotContains(second_visit, "Your API key is ready")

    def test_regenerate_key_invalidates_previous_key(self):
        old_key = self.project.plaintext_api_key
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("monitoring:project_regenerate_key", args=[self.project.pk])
        )
        self.assertEqual(response.status_code, 200)
        new_key = response.context["api_key"]
        self.assertNotEqual(new_key, old_key)
        self.project.refresh_from_db()
        self.assertTrue(self.project.authenticate_api_key(new_key))
        self.assertFalse(self.project.authenticate_api_key(old_key))

    def test_regenerate_key_is_post_only_and_owner_scoped(self):
        self.client.force_login(self.stranger)
        response = self.client.get(
            reverse("monitoring:project_regenerate_key", args=[self.project.pk])
        )
        self.assertEqual(response.status_code, 405)

    def test_project_delete_is_post_only(self):
        self.client.force_login(self.owner)
        url = reverse("monitoring:project_delete", args=[self.project.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(
            self.owner.monitoring_projects.filter(pk=self.project.pk).exists()
        )

    def test_project_dashboard_renders_with_metrics(self):
        create_event(self.project, status_code=200, response_time=100)
        create_event(self.project, status_code=500, response_time=900)
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("monitoring:project_dashboard", args=[self.project.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["success_events"], 1)
        self.assertEqual(response.context["error_events"], 1)
        self.assertEqual(response.context["total_events"], 2)


class EventViewTests(TestCase):
    def setUp(self):
        self.owner = create_user("eventviewowner")
        self.stranger = create_user("eventviewstranger")
        self.project = create_project(self.owner, "Events project")
        self.success = create_event(self.project, status_code=200, response_time=50)
        self.failure = create_event(
            self.project,
            event_type=Event.EventType.APPLICATION_ERROR,
            status_code=500,
            response_time=800,
        )

    def test_event_list_is_owner_scoped(self):
        self.client.force_login(self.stranger)
        response = self.client.get(
            reverse("monitoring:event_list", args=[self.project.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_event_list_filters(self):
        self.client.force_login(self.owner)
        url = reverse("monitoring:event_list", args=[self.project.pk])
        response = self.client.get(url, {"event_type": Event.EventType.APPLICATION_ERROR})
        self.assertEqual(
            [event.pk for event in response.context["events"]], [self.failure.pk]
        )
        response = self.client.get(url, {"status_code": "200"})
        self.assertEqual(
            [event.pk for event in response.context["events"]], [self.success.pk]
        )
        response = self.client.get(url, {"service": "no-such-service"})
        self.assertEqual(list(response.context["events"]), [])

    def test_event_detail_is_owner_scoped(self):
        self.client.force_login(self.stranger)
        response = self.client.get(
            reverse("monitoring:event_detail", args=[self.project.pk, self.success.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_csv_export_contains_events_and_respects_filters(self):
        self.client.force_login(self.owner)
        url = reverse("monitoring:event_export", args=[self.project.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0][:3], ["id", "event_type", "custom_event_name"])
        self.assertEqual(len(rows) - 1, 2)

        filtered = self.client.get(url, {"status_code": "200"})
        filtered_rows = list(
            csv.reader(io.StringIO(filtered.content.decode("utf-8-sig")))
        )
        self.assertEqual(len(filtered_rows) - 1, 1)

    def test_csv_export_is_owner_scoped(self):
        self.client.force_login(self.stranger)
        response = self.client.get(
            reverse("monitoring:event_export", args=[self.project.pk])
        )
        self.assertEqual(response.status_code, 404)


class AlertRuleViewTests(TestCase):
    def setUp(self):
        self.owner = create_user("alertowner")
        self.stranger = create_user("alertstranger")
        self.project = create_project(self.owner, "Alert project")
        self.rule = create_alert_rule(self.project)

    def test_alert_rule_creation_is_owner_scoped(self):
        self.client.force_login(self.stranger)
        response = self.client.get(
            reverse("monitoring:alert_create", args=[self.project.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_alert_rule_creation_and_toggle(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("monitoring:alert_create", args=[self.project.pk]),
            {
                "name": "New rule",
                "metric": AlertRule.Metric.ERROR_RATE,
                "condition": AlertRule.Condition.GT,
                "threshold": "10.5",
                "time_window_minutes": "30",
                "cooldown_minutes": "15",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        rule = self.project.alert_rules.get(name="New rule")
        self.assertEqual(rule.threshold, Decimal("10.5000"))
        self.assertEqual(rule.project, self.project)

        toggle_url = reverse(
            "monitoring:alert_toggle", args=[self.project.pk, rule.pk]
        )
        self.client.post(toggle_url)
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)

    def test_alert_toggle_is_post_only(self):
        self.client.force_login(self.owner)
        url = reverse("monitoring:alert_toggle", args=[self.project.pk, self.rule.pk])
        self.assertEqual(self.client.get(url).status_code, 405)


class ProcessEventTaskTests(TestCase):
    def setUp(self):
        self.owner = create_user("taskowner")
        self.project = create_project(self.owner, "Task project")

    def test_error_count_rule_creates_trigger_and_notification(self):
        rule = create_alert_rule(
            self.project,
            metric=AlertRule.Metric.ERROR_COUNT,
            condition=AlertRule.Condition.GTE,
            threshold=Decimal("2"),
            time_window_minutes=60,
            cooldown_minutes=0,
        )
        events = [
            create_event(
                self.project,
                status_code=500,
                created_at=hours_ago(0.1 * (index + 1)),
            )
            for index in range(2)
        ]
        result = process_event(events[-1].pk)
        self.assertEqual(result["triggers_created"], 1)
        self.assertTrue(
            AlertTrigger.objects.filter(rule=rule, project=self.project).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.owner,
                notification_type=Notification.NotificationType.ERROR_ALERT,
            ).exists()
        )

    def test_condition_not_met_creates_no_trigger(self):
        create_alert_rule(
            self.project,
            metric=AlertRule.Metric.ERROR_COUNT,
            condition=AlertRule.Condition.GTE,
            threshold=Decimal("50"),
            time_window_minutes=60,
        )
        event = create_event(self.project, status_code=500)
        result = process_event(event.pk)
        self.assertEqual(result["triggers_created"], 0)
        self.assertEqual(AlertTrigger.objects.count(), 0)

    def test_missing_event_is_handled(self):
        result = process_event(999999)
        self.assertEqual(result["triggers_created"], 0)

    def test_inactive_rule_never_triggers(self):
        create_alert_rule(
            self.project,
            metric=AlertRule.Metric.ERROR_COUNT,
            condition=AlertRule.Condition.GTE,
            threshold=Decimal("1"),
            time_window_minutes=60,
            is_active=False,
        )
        event = create_event(self.project, status_code=503)
        result = process_event(event.pk)
        self.assertEqual(result["triggers_created"], 0)

    def test_error_rate_rule(self):
        create_alert_rule(
            self.project,
            metric=AlertRule.Metric.ERROR_RATE,
            condition=AlertRule.Condition.GT,
            threshold=Decimal("40"),
            time_window_minutes=60,
            cooldown_minutes=0,
        )
        create_event(self.project, status_code=500, created_at=hours_ago(0.1))
        event = create_event(self.project, status_code=200, created_at=hours_ago(0.05))
        result = process_event(event.pk)
        self.assertEqual(result["triggers_created"], 1)


class SpikeAndCleanupTaskTests(TestCase):
    def setUp(self):
        self.owner = create_user("spikeowner")
        self.project = create_project(self.owner, "Spike project")

    def test_error_spike_detector_creates_single_trigger(self):
        for index in range(4):
            create_event(self.project, status_code=500, created_at=hours_ago(0.02 * (index + 1)))
        with override_settings(ERROR_SPIKE_THRESHOLD=3, ERROR_SPIKE_MULTIPLIER=3.0):
            result = detect_abnormal_error_spikes()
        self.assertEqual(result["triggers_created"], 1)
        self.assertEqual(
            AlertTrigger.objects.filter(rule__isnull=True).count(), 1
        )
        with override_settings(ERROR_SPIKE_THRESHOLD=3, ERROR_SPIKE_MULTIPLIER=3.0):
            second_run = detect_abnormal_error_spikes()
        self.assertEqual(second_run["triggers_created"], 0)

    def test_no_spike_when_error_volume_is_low(self):
        create_event(self.project, status_code=500, created_at=hours_ago(0.05))
        result = detect_abnormal_error_spikes()
        self.assertEqual(result["triggers_created"], 0)

    def test_cleanup_removes_old_events(self):
        old = create_event(
            self.project, created_at=timezone.now() - timedelta(days=200)
        )
        recent = create_event(self.project)
        result = cleanup_old_events(90)
        self.assertEqual(result["deleted_event_count"], 1)
        self.assertFalse(Event.objects.filter(pk=old.pk).exists())
        self.assertTrue(Event.objects.filter(pk=recent.pk).exists())


class NotificationViewTests(TestCase):
    def setUp(self):
        self.owner = create_user("notifyowner")
        self.stranger = create_user("notifystranger")
        self.project = create_project(self.owner, "Notification project")
        self.notification = create_notification(self.owner, self.project)

    def test_history_is_user_scoped(self):
        stranger_notification = create_notification(
            self.stranger, title="Stranger only"
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("notifications:history"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.notification.title)
        self.assertNotContains(response, stranger_notification.title)

    def test_mark_read_is_owner_scoped(self):
        self.client.force_login(self.stranger)
        url = reverse(
            "notifications:mark_read", args=[self.notification.pk]
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.notification.refresh_from_db()
        self.assertFalse(self.notification.is_read)

    def test_mark_read_marks_the_notification(self):
        self.client.force_login(self.owner)
        url = reverse("notifications:mark_read", args=[self.notification.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.is_read)

    def test_mark_all_read(self):
        create_notification(self.owner, self.project, title="Second")
        self.client.force_login(self.owner)
        url = reverse("notifications:mark_all_read")
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(
            Notification.objects.filter(user=self.owner, is_read=False).count(), 0
        )
