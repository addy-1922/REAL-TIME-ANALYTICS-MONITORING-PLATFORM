import json

from channels.testing import WebsocketCommunicator
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from monitoring.models import Event
from tests.factories import create_event, create_project, create_user


class DashboardViewTests(TestCase):
    def setUp(self):
        self.owner = create_user("dashowner")
        self.stranger = create_user("dashstranger")
        self.project = create_project(self.owner, "Dashboard project")
        cache.clear()
        create_event(self.project, status_code=200, response_time=100)
        create_event(self.project, status_code=500, response_time=900)

    def test_overview_counts_and_health(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["overview"]["total"], 2)
        self.assertEqual(response.context["overview"]["errors"], 1)
        self.assertEqual(response.context["active_project_count"], 1)

        health = self.client.get(reverse("dashboard:health"))
        self.assertEqual(health.status_code, 200)
        self.assertEqual(json.loads(health.content), {"status": "ok"})

    def test_overview_excludes_other_users_projects(self):
        stranger_project = create_project(self.stranger, "Hidden project")
        create_event(stranger_project, status_code=500)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(response.context["overview"]["total"], 2)
        self.assertNotContains(response, "Hidden project")

    def test_project_filter_is_applied(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("dashboard:overview"), {"project": self.project.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_project"], self.project)

    def test_health_is_public(self):
        response = self.client.get(reverse("dashboard:health"))
        self.assertEqual(response.status_code, 200)

    def test_error_pages_render(self):
        self.client.force_login(self.owner)
        response = self.client.get("/definitely-missing-page/")
        self.assertEqual(response.status_code, 404)

    def test_admin_requires_staff(self):
        response = self.client.get(reverse("admin:index"))
        self.assertIn(response.status_code, (302, 200))
        if response.status_code == 200:
            self.assertContains(response, "Site administration")


class WebSocketTests(TransactionTestCase):
    def setUp(self):
        self.owner = create_user("wsowner")
        self.stranger = create_user("wsstranger")
        self.project = create_project(self.owner, "WS project")
        cache.clear()

    async def _connect_consumer(self, consumer_app, path, user, url_kwargs=None):
        communicator = WebsocketCommunicator(consumer_app, path)
        scope = dict(communicator.scope)
        scope["user"] = user
        scope["url_route"] = {"kwargs": url_kwargs or {}}
        communicator.scope = scope
        connected, _ = await communicator.connect()
        return communicator, connected

    async def test_project_stream_rejects_unauthenticated(self):
        from django.contrib.auth.models import AnonymousUser

        from monitoring.consumers import ProjectStreamConsumer

        communicator, connected = await self._connect_consumer(
            ProjectStreamConsumer.as_asgi(),
            f"/ws/projects/{self.project.pk}/stream/",
            AnonymousUser(),
            {"project_pk": str(self.project.pk)},
        )
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_project_stream_rejects_non_owner(self):
        from monitoring.consumers import ProjectStreamConsumer

        communicator, connected = await self._connect_consumer(
            ProjectStreamConsumer.as_asgi(),
            f"/ws/projects/{self.project.pk}/stream/",
            self.stranger,
            {"project_pk": str(self.project.pk)},
        )
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_owner_receives_broadcast_events(self):
        from channels.layers import get_channel_layer

        from monitoring.consumers import ProjectStreamConsumer

        communicator, connected = await self._connect_consumer(
            ProjectStreamConsumer.as_asgi(),
            f"/ws/projects/{self.project.pk}/stream/",
            self.owner,
            {"project_pk": str(self.project.pk)},
        )
        self.assertTrue(connected)

        await get_channel_layer().group_send(
            f"monitoring_project_{self.project.pk}",
            {
                "type": "monitoring.event",
                "event": {
                    "id": 4242,
                    "status_code": 500,
                    "event_type": "API_REQUEST",
                    "message": "live",
                },
            },
        )
        message = await communicator.receive_json_from()
        self.assertEqual(message["type"], "monitoring.event")
        self.assertEqual(message["payload"]["id"], 4242)
        self.assertEqual(message["payload"]["status_code"], 500)
        await communicator.disconnect()

    async def test_user_notification_stream_is_scoped_to_the_owner(self):
        from monitoring.consumers import UserNotificationConsumer

        stranger_communicator, stranger_connected = await self._connect_consumer(
            UserNotificationConsumer.as_asgi(),
            f"/ws/users/{self.owner.pk}/notifications/",
            self.stranger,
            {"user_pk": str(self.owner.pk)},
        )
        self.assertFalse(stranger_connected)
        await stranger_communicator.disconnect()

        communicator, connected = await self._connect_consumer(
            UserNotificationConsumer.as_asgi(),
            f"/ws/users/{self.owner.pk}/notifications/",
            self.owner,
            {"user_pk": str(self.owner.pk)},
        )
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_notification_stream_receives_notifications(self):
        from channels.layers import get_channel_layer

        from notifications.consumers import NotificationConsumer

        communicator, connected = await self._connect_consumer(
            NotificationConsumer.as_asgi(), "/ws/notifications/", self.owner
        )
        self.assertTrue(connected)

        await get_channel_layer().group_send(
            f"user_{self.owner.pk}",
            {
                "type": "notification_message",
                "notification": {
                    "id": 77,
                    "title": "Live",
                    "message": "Hello",
                    "notification_type": "ERROR_ALERT",
                    "is_read": False,
                },
            },
        )
        message = await communicator.receive_json_from()
        self.assertEqual(message["id"], 77)
        self.assertEqual(message["title"], "Live")
        await communicator.disconnect()


class SeedCommandTests(TestCase):
    def test_seed_demo_data_creates_demo_content(self):
        from io import StringIO

        from django.core.management import call_command

        output = StringIO()
        call_command("seed_demo_data", events=40, days=3, stdout=output)
        text = output.getvalue()
        self.assertIn("Demo data seeded successfully", text)
        self.assertIn("DemoPass123!", text)
        self.assertGreater(Event.objects.count(), 0)

    def test_seed_demo_data_owner_uses_existing_projects(self):
        from io import StringIO

        from django.contrib.auth import get_user_model
        from django.core.management import call_command

        from monitoring.models import Project

        owner = get_user_model().objects.create_user(
            username="seedowner", password="pw-12345"
        )
        project = Project.objects.create(owner=owner, name="Existing Project")

        output = StringIO()
        call_command(
            "seed_demo_data", owner="seedowner", events=25, days=2, stdout=output
        )

        text = output.getvalue()
        self.assertIn("Using existing user 'seedowner'", text)
        self.assertIn("Using 1 existing project(s) for seedowner", text)
        self.assertNotIn("DemoPass123!", text)
        self.assertEqual(project.events.count(), 25)
        self.assertEqual(Project.objects.filter(owner=owner).count(), 1)

    def test_seed_demo_data_owner_rejects_unknown_user(self):
        from io import StringIO

        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command(
                "seed_demo_data", owner="nobody-here", events=5, stdout=StringIO()
            )

    def test_seed_demo_data_reset_is_scoped_to_owner(self):
        from io import StringIO

        from django.contrib.auth import get_user_model
        from django.core.management import call_command

        from monitoring.models import Project

        keeper = get_user_model().objects.create_user(
            username="keeper", password="pw-12345"
        )
        kept_project = Project.objects.create(owner=keeper, name="Keep Me")
        kept_event = Event.objects.create(
            project=kept_project,
            event_type=Event.EventType.API_REQUEST,
            message="survivor",
            status_code=200,
        )

        target = get_user_model().objects.create_user(
            username="target", password="pw-12345"
        )
        doomed = Project.objects.create(owner=target, name="Delete Me")
        Event.objects.create(
            project=doomed,
            event_type=Event.EventType.API_REQUEST,
            message="doomed",
            status_code=200,
        )

        call_command(
            "seed_demo_data", owner="target", events=10, days=1, reset=True,
            stdout=StringIO(),
        )

        self.assertTrue(Project.objects.filter(pk=kept_project.pk).exists())
        self.assertTrue(Event.objects.filter(pk=kept_event.pk).exists())
        self.assertFalse(Project.objects.filter(pk=doomed.pk).exists())
        self.assertFalse(
            Project.objects.filter(owner=target, name="Delete Me").exists()
        )
        # Reset removes the account's projects, so the blueprint projects are
        # recreated and receive the freshly generated events.
        replacement_projects = Project.objects.filter(owner=target)
        self.assertEqual(replacement_projects.count(), 2)
        self.assertEqual(
            Event.objects.filter(project__owner=target).count(), 10
        )
        self.assertEqual(kept_project.events.count(), 1)
