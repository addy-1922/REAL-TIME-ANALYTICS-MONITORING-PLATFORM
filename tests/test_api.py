import json
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from analytics.services import increment_cache_version
from monitoring.models import AlertRule, Event
from notifications.models import Notification
from tests.factories import (
    create_alert_rule,
    create_event,
    create_notification,
    create_project,
    create_user,
)


class ApiKeyIngestionTests(TestCase):
    def setUp(self):
        self.owner = create_user("apiowner")
        self.project = create_project(self.owner, "Ingest project")
        self.api_key = self.project.plaintext_api_key
        self.url = reverse("api:events-list")
        self.payload = {
            "event_type": "API_REQUEST",
            "message": "GET /api/orders 200",
            "service": "api-gateway",
            "environment": "production",
            "status_code": 200,
            "response_time": 120,
            "metadata": {"path": "/api/orders", "method": "GET"},
        }
        cache.clear()

    def test_requires_api_key(self):
        response = self.client.post(self.url, self.payload, content_type="application/json")
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json())

    def test_rejects_invalid_api_key(self):
        response = self.client.post(
            self.url,
            self.payload,
            content_type="application/json",
            HTTP_X_API_KEY="rt_live_invalid.invalid",
        )
        self.assertEqual(response.status_code, 401)

    def test_creates_event_with_valid_key(self):
        response = self.client.post(
            self.url,
            self.payload,
            content_type="application/json",
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["project"], self.project.pk)
        self.assertEqual(body["status_code"], 200)
        self.assertEqual(self.project.events.count(), 1)
        created = self.project.events.get()
        self.assertEqual(created.service, "api-gateway")
        self.assertEqual(created.ip_address, "127.0.0.1")

    def test_supports_authorization_apikey_header(self):
        response = self.client.post(
            self.url,
            self.payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"ApiKey {self.api_key}",
        )
        self.assertEqual(response.status_code, 201)

    def test_inactive_project_cannot_ingest(self):
        self.project.is_active = False
        self.project.save(update_fields=["is_active"])
        response = self.client.post(
            self.url,
            self.payload,
            content_type="application/json",
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 401)

    def test_rejects_project_id_mismatch(self):
        other = create_project(self.owner, "Other project")
        response = self.client.post(
            self.url,
            {**self.payload, "project_id": other.pk},
            content_type="application/json",
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 403)

    def test_allows_matching_project_id(self):
        response = self.client.post(
            self.url,
            {**self.payload, "project_id": self.project.pk},
            content_type="application/json",
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 201)

    def test_validation_errors_are_structured(self):
        response = self.client.post(
            self.url,
            {**self.payload, "status_code": 99},
            content_type="application/json",
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertIn("error", body)
        self.assertIn("details", body["error"])

    def test_custom_event_requires_name(self):
        response = self.client.post(
            self.url,
            {**self.payload, "event_type": "CUSTOM"},
            content_type="application/json",
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("custom_event_name", response.json()["error"]["details"])

    def test_environment_choices_are_enforced(self):
        response = self.client.post(
            self.url,
            {**self.payload, "environment": "moon-base"},
            content_type="application/json",
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 400)

    def test_get_requires_session_authentication(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_get_lists_only_owner_events(self):
        create_event(self.project, status_code=200)
        stranger = create_user("apistranger")
        stranger_project = create_project(stranger, "Stranger project")
        create_event(stranger_project, status_code=200)
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)


class ApiReadTests(TestCase):
    def setUp(self):
        self.owner = create_user("apiread")
        self.stranger = create_user("apireadstranger")
        self.project = create_project(self.owner, "Read project")
        self.stranger_project = create_project(self.stranger, "Stranger project")
        self.event = create_event(self.project, status_code=200, response_time=100)
        self.stranger_event = create_event(self.stranger_project, status_code=200)
        cache.clear()

    def test_projects_list_is_owner_scoped(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("api:projects-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], self.project.pk)

    def test_project_detail_hides_api_key(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("api:projects-detail", args=[self.project.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("api_key", response.json())
        self.assertNotIn(self.project.api_key_hash, response.content.decode())

    def test_project_detail_is_owner_scoped(self):
        self.client.force_login(self.stranger)
        response = self.client.get(
            reverse("api:projects-detail", args=[self.project.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_project_create_returns_key_once(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("api:projects-list"),
            {"name": "API created", "description": "from api"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertIn("api_key", body)
        self.assertTrue(body["api_key"].startswith("rt_live_"))

        detail = self.client.get(
            reverse("api:projects-detail", args=[body["id"]])
        )
        self.assertNotIn("api_key", detail.json())

    def test_event_list_filters(self):
        create_event(self.project, status_code=500, response_time=900)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("api:events-list"), {"status_code": 500})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    def test_analytics_endpoint(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("api:analytics"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["overview"]["total"], 1)
        self.assertIn("timeline", body)
        self.assertIn("event_types", body)

    def test_analytics_endpoint_rejects_bad_filters(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("api:analytics"),
            {"date_from": "2024-05-10", "date_to": "2024-05-01"},
        )
        self.assertEqual(response.status_code, 400)

    def test_alerts_crud_is_owner_scoped(self):
        self.client.force_login(self.owner)
        create_alert_rule(self.project)
        create_alert_rule(self.stranger_project, name="Stranger rule")
        response = self.client.get(reverse("api:alerts-list"))
        self.assertEqual(response.json()["count"], 1)

        created = self.client.post(
            reverse("api:alerts-list"),
            {
                "project": self.project.pk,
                "name": "API rule",
                "metric": "ERROR_RATE",
                "condition": "GT",
                "threshold": "10",
                "time_window_minutes": 30,
                "cooldown_minutes": 10,
            },
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        rule_id = created.json()["id"]

        updated = self.client.patch(
            reverse("api:alerts-detail", args=[rule_id]),
            {"is_active": False},
            content_type="application/json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.json()["is_active"])

        self.assertEqual(
            self.client.delete(
                reverse("api:alerts-detail", args=[rule_id])
            ).status_code,
            204,
        )

    def test_alert_creation_cannot_target_other_users_project(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("api:alerts-list"),
            {
                "project": self.stranger_project.pk,
                "name": "Hostile rule",
                "metric": "ERROR_COUNT",
                "condition": "GT",
                "threshold": "1",
                "time_window_minutes": 5,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_notifications_are_user_scoped(self):
        create_notification(self.owner, self.project, title="Mine")
        create_notification(self.stranger, title="Theirs")
        self.client.force_login(self.owner)
        response = self.client.get(reverse("api:notifications-list"))
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["title"], "Mine")

    def test_notification_read_endpoint(self):
        notification = create_notification(self.owner, self.project)
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("api:notifications-read", args=[notification.pk])
        )
        self.assertEqual(response.status_code, 200)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_notification_read_cannot_target_other_users(self):
        notification = create_notification(self.stranger, title="Theirs")
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("api:notifications-read", args=[notification.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_schema_and_docs_are_public(self):
        self.assertEqual(self.client.get(reverse("api:schema")).status_code, 200)
        self.assertEqual(self.client.get(reverse("api:docs")).status_code, 200)


class CacheInvalidationTests(TestCase):
    def setUp(self):
        self.owner = create_user("cacheowner")
        self.project = create_project(self.owner, "Cache project")
        cache.clear()

    def test_event_ingestion_bumps_cache_version(self):
        from analytics.services import get_cache_version

        version = get_cache_version(project=self.project)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("api:events-list"),
                {
                    "event_type": "API_REQUEST",
                    "message": "cache test",
                    "service": "api",
                    "environment": "production",
                    "status_code": 200,
                },
                content_type="application/json",
                HTTP_X_API_KEY=self.project.plaintext_api_key,
            )
        self.assertGreater(get_cache_version(project=self.project), version)
