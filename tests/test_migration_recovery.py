import os
import sys
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase

from accounts.management.commands.reset_render_database import (
    find_inconsistent_migrations,
    running_under_test_runner,
)

CONFIRMATION_ENV_VAR = "RESET_RENDER_DATABASE"


def environment(**overrides):
    values = {k: v for k, v in os.environ.items() if k != CONFIRMATION_ENV_VAR}
    values.update(overrides)
    return values


class ResetRenderDatabaseGuardTests(TestCase):
    """The recovery command must never act without the explicit confirmation."""

    def test_refuses_when_the_confirmation_variable_is_absent(self):
        with mock.patch.dict(os.environ, environment(), clear=True):
            with self.assertRaisesMessage(
                CommandError, "RESET_RENDER_DATABASE is not set to"
            ):
                call_command("reset_render_database", verbosity=0)

    def test_refuses_for_every_other_confirmation_value(self):
        for value in ("", "false", "0", "1", "yes", "please", "truthy"):
            with self.subTest(value=value):
                with mock.patch.dict(
                    os.environ, environment(**{CONFIRMATION_ENV_VAR: value}), clear=True
                ):
                    with self.assertRaisesMessage(
                        CommandError, "RESET_RENDER_DATABASE is not set to"
                    ):
                        call_command("reset_render_database", verbosity=0)

    def test_refuses_to_run_against_sqlite(self):
        with mock.patch.dict(
            os.environ, environment(**{CONFIRMATION_ENV_VAR: "true"}), clear=True
        ):
            with self.assertRaisesMessage(CommandError, "Refusing to reset a sqlite"):
                call_command("reset_render_database", verbosity=0)

    def test_a_refused_run_leaves_the_database_untouched(self):
        tables_before = set(connections["default"].introspection.table_names())
        with mock.patch.dict(os.environ, environment(), clear=True):
            with self.assertRaises(CommandError):
                call_command("reset_render_database", verbosity=0)
        tables_after = set(connections["default"].introspection.table_names())
        self.assertEqual(tables_before, tables_after)
        self.assertIn("auth_user", tables_after)
        self.assertIn("django_migrations", tables_after)

    def test_detects_the_test_subcommand(self):
        with mock.patch.object(sys, "argv", ["manage.py", "test", "tests"]):
            self.assertTrue(running_under_test_runner())
        with mock.patch.object(sys, "argv", ["manage.py", "migrate", "--noinput"]):
            self.assertFalse(running_under_test_runner())


class InconsistentMigrationDetectionTests(TestCase):
    """Detection reads django_migrations; it is the gate the reset depends on."""

    def test_a_migrated_database_reports_nothing(self):
        self.assertEqual(find_inconsistent_migrations(connections["default"]), [])

    def test_detects_notifications_applied_before_monitoring(self):
        MigrationRecorder(connections["default"]).migration_qs.filter(
            app="monitoring"
        ).delete()

        inconsistent = find_inconsistent_migrations(connections["default"])
        self.assertIn(
            (("notifications", "0001_initial"), ("monitoring", "0001_initial")),
            inconsistent,
        )
        self.assertIn(
            (("analytics", "0001_initial"), ("monitoring", "0001_initial")),
            inconsistent,
        )
