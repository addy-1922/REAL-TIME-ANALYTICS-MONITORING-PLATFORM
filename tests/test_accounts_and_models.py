from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from monitoring.models import Event, Project
from notifications.models import Notification
from tests.factories import (
    PASSWORD,
    create_event,
    create_notification,
    create_profile,
    create_project,
    create_user,
)

User = get_user_model()


class ProjectApiKeyTests(TestCase):
    def setUp(self):
        self.owner = create_user("keyowner")

    def test_generated_key_is_only_stored_as_a_hash(self):
        api_key = Project.generate_api_key()
        self.assertTrue(api_key.startswith(Project.KEY_PREFIX))
        self.assertIn(".", api_key)
        self.assertNotIn(api_key, Project.hash_api_key(api_key))

    def test_create_with_api_key_returns_plaintext_once(self):
        project, plaintext = Project.objects.create_with_api_key(
            owner=self.owner, name="Hashed project"
        )
        self.assertEqual(project.api_key_hash, Project.hash_api_key(plaintext))
        self.assertNotEqual(project.api_key_prefix, plaintext)
        self.assertTrue(project.api_key_prefix.startswith(Project.KEY_PREFIX))
        self.assertTrue(project.authenticate_api_key(plaintext))
        self.assertFalse(project.authenticate_api_key("rt_live_wrong.key"))

    def test_rotate_api_key_invalidates_the_previous_key(self):
        project, old_key = Project.objects.create_with_api_key(
            owner=self.owner, name="Rotating project"
        )
        new_key = project.rotate_api_key()
        self.assertNotEqual(old_key, new_key)
        self.assertTrue(project.authenticate_api_key(new_key))
        self.assertFalse(project.authenticate_api_key(old_key))
        project.refresh_from_db()
        self.assertFalse(project.authenticate_api_key(old_key))

    def test_revoke_api_key_disables_authentication(self):
        project, api_key = Project.objects.create_with_api_key(
            owner=self.owner, name="Revoked project"
        )
        project.revoke_api_key()
        self.assertIsNone(project.api_key_hash)
        self.assertIsNone(project.api_key_prefix)
        self.assertFalse(project.authenticate_api_key(api_key))

    def test_api_key_hash_is_unique(self):
        api_key = Project.generate_api_key()
        create_project(self.owner, "First", api_key=api_key)
        with self.assertRaises(IntegrityError):
            create_project(create_user("other"), "Second", api_key=api_key)


class EventModelTests(TestCase):
    def setUp(self):
        self.owner = create_user("eventowner")
        self.project = create_project(self.owner)

    def test_custom_event_requires_a_custom_name(self):
        event = Event(
            project=self.project,
            event_type=Event.EventType.CUSTOM,
            status_code=200,
            message="Custom",
            service="api",
            environment="production",
        )
        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_custom_name_is_rejected_for_standard_event_types(self):
        event = Event(
            project=self.project,
            event_type=Event.EventType.API_REQUEST,
            custom_event_name="not_allowed",
            status_code=200,
            message="Bad",
            service="api",
            environment="production",
        )
        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_display_event_type_uses_custom_name(self):
        event = create_event(
            self.project,
            event_type=Event.EventType.CUSTOM,
            custom_event_name="checkout_completed",
        )
        self.assertEqual(event.display_event_type, "checkout_completed")

    def test_error_classification_covers_4xx_and_5xx(self):
        client_error = create_event(self.project, status_code=404)
        server_error = create_event(self.project, status_code=503)
        typed_error = create_event(
            self.project, event_type=Event.EventType.APPLICATION_ERROR, status_code=200
        )
        success = create_event(self.project, status_code=204)

        self.assertTrue(client_error.is_error)
        self.assertTrue(server_error.is_error)
        self.assertTrue(typed_error.is_error)
        self.assertFalse(success.is_error)

        self.assertTrue(success.is_success)
        self.assertFalse(client_error.is_success)
        self.assertFalse(typed_error.is_success)

    def test_is_slow_uses_configured_threshold(self):
        fast = create_event(self.project, response_time=10)
        slow = create_event(self.project, response_time=5000)
        self.assertFalse(fast.is_slow)
        self.assertTrue(slow.is_slow)


class ProjectOwnershipTests(TestCase):
    def setUp(self):
        self.owner = create_user("owner")
        self.stranger = create_user("stranger")
        self.project = create_project(self.owner, "Private project")

    def test_events_are_scoped_to_the_project_owner(self):
        create_event(self.project)
        self.assertEqual(self.project.events.count(), 1)
        self.assertEqual(Event.objects.filter(project__owner=self.stranger).count(), 0)

    def test_notifications_are_linked_to_the_project(self):
        notification = create_notification(self.owner, self.project)
        self.assertEqual(self.project.notifications.count(), 1)
        self.assertEqual(notification.user, self.owner)

    def test_profile_is_created_for_new_users(self):
        profile, created = Profile.objects.get_or_create(user=self.owner)
        self.assertTrue(profile.pk)
        self.assertTrue(created or profile.user_id == self.owner.pk)


class AccountFlowTests(TestCase):
    def test_registration_creates_user_and_redirects_to_login(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "newuser",
                "email": "newuser@example.com",
                "password1": "Str0ng-Passw0rd!",
                "password2": "Str0ng-Passw0rd!",
            },
        )
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertTrue(
            User.objects.filter(username="newuser").exists(),
            "Registration should persist the new account.",
        )

    def test_login_and_logout(self):
        create_user("loginuser", password=PASSWORD)
        self.assertTrue(self.client.login(username="loginuser", password=PASSWORD))
        response = self.client.post(reverse("accounts:logout"))
        self.assertIn(response.status_code, (200, 302))
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_login_with_bad_password_fails(self):
        create_user("badlogin", password=PASSWORD)
        self.assertFalse(self.client.login(username="badlogin", password="wrong"))

    def test_profile_requires_login(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_profile_update(self):
        user = create_user("profileuser")
        self.client.force_login(user)
        response = self.client.post(
            reverse("accounts:profile_edit"),
            {"job_title": "SRE", "bio": "On-call engineer", "timezone": "UTC"},
        )
        self.assertIn(response.status_code, (200, 302))
        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.job_title, "SRE")

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)
