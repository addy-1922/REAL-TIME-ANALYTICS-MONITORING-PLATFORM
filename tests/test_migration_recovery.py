import os
import sys
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError, OutputWrapper
from django.db import connections
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase

from accounts.management.commands.reset_render_migrations import (
    Command,
    running_under_test_runner,
)

CONFIRMATION_ENV_VAR = "RESET_RENDER_DATABASE"


def environment(**overrides):
    values = {k: v for k, v in os.environ.items() if k != CONFIRMATION_ENV_VAR}
    values.update(overrides)
    return values


def table_names():
    return set(connections["default"].introspection.table_names())


class ResetRenderMigrationsGuardTests(TestCase):
    """The recovery command must abort without touching anything by default."""

    def test_refuses_when_the_confirmation_variable_is_absent(self):
        before = table_names()
        with mock.patch.dict(os.environ, environment(), clear=True):
            with self.assertRaisesMessage(
                CommandError, "RESET_RENDER_DATABASE is not set to"
            ):
                call_command("reset_render_migrations", verbosity=0)
        self.assertEqual(table_names(), before)

    def test_refuses_for_every_other_confirmation_value(self):
        before = table_names()
        for value in ("", "false", "0", "1", "yes", "True", "TRUE", "please"):
            with self.subTest(value=value):
                with mock.patch.dict(
                    os.environ, environment(**{CONFIRMATION_ENV_VAR: value}), clear=True
                ):
                    with self.assertRaisesMessage(
                        CommandError, "RESET_RENDER_DATABASE is not set to"
                    ):
                        call_command("reset_render_migrations", verbosity=0)
        self.assertEqual(table_names(), before)

    def test_refuses_to_run_against_sqlite(self):
        with mock.patch.dict(
            os.environ, environment(**{CONFIRMATION_ENV_VAR: "true"}), clear=True
        ):
            with self.assertRaisesMessage(CommandError, "Refusing to reset a sqlite"):
                call_command("reset_render_migrations", verbosity=0)

    def test_detects_the_test_subcommand(self):
        with mock.patch.object(sys, "argv", ["manage.py", "test", "tests"]):
            self.assertTrue(running_under_test_runner())
        with mock.patch.object(sys, "argv", ["manage.py", "migrate", "--noinput"]):
            self.assertFalse(running_under_test_runner())


class InconsistentStateCheckTests(TestCase):
    """The state check is the gate the whole command depends on."""

    def _command(self):
        return Command(stdout=OutputWrapper(StringIO()))
    def test_accepts_the_reported_state(self):
        command = self._command()
        command._require_inconsistent_state({("notifications", "0001_initial")})

    def test_rejects_a_history_where_the_dependency_is_applied(self):
        command = self._command()
        applied = {("notifications", "0001_initial"), ("monitoring", "0001_initial")}
        with self.assertRaisesMessage(
            CommandError, "monitoring.0001_initial is already applied"
        ):
            command._require_inconsistent_state(applied)

    def test_rejects_a_history_without_the_inconsistent_migration(self):
        command = self._command()
        with self.assertRaisesMessage(
            CommandError, "notifications.0001_initial is not recorded as applied"
        ):
            command._require_inconsistent_state({("monitoring", "0001_initial")})

    def test_a_fully_migrated_test_database_holds_both_migrations(self):
        applied = set(MigrationRecorder(connections["default"]).applied_migrations())
        self.assertIn(("notifications", "0001_initial"), applied)
        self.assertIn(("monitoring", "0001_initial"), applied)

    def test_the_render_state_can_be_reproduced_for_manual_verification(self):
        recorder = MigrationRecorder(connections["default"])
        recorder.migration_qs.filter(app="monitoring").delete()
        applied = set(recorder.applied_migrations())
        self.assertIn(("notifications", "0001_initial"), applied)
        self.assertNotIn(("monitoring", "0001_initial"), applied)
