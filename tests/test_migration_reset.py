from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django.test import TransactionTestCase

PROBE_ALIAS = "reset_probe"


class ResetMigrationsCommandTests(TransactionTestCase):
    """The reset command is manual, destructive, and refuses to guess.

    The command is exercised against the throwaway ``reset_probe`` alias from
    ``config.settings_test`` because it drops every Django table in the database
    it targets.
    """

    databases = {"default", PROBE_ALIAS}

    def setUp(self):
        self.probe = connections[PROBE_ALIAS]
        self._rebuild_probe_database()
        self.probe_migrations = MigrationRecorder(self.probe)

    def _rebuild_probe_database(self):
        """Leave the probe database with an empty schema, then migrate from scratch.

        Django's test ``flush`` keeps the ``django_migrations`` rows, so the
        recorder is dropped explicitly to keep each test independent.
        """
        tables = set(
            self.probe.introspection.django_table_names(
                only_existing=True, include_views=False
            )
        )
        tables.add(MigrationRecorder(self.probe).Migration._meta.db_table)
        tables.add("legacy_ingest")
        with self.probe.cursor() as cursor:
            for table in sorted(tables):
                cursor.execute(f'DROP TABLE IF EXISTS "{table}"')
        call_command("migrate", database=PROBE_ALIAS, verbosity=0)

    def _simulate_inconsistent_history(self):
        """Reproduce the reported state: notifications applied, monitoring not."""
        self.probe_migrations.migration_qs.filter(app="monitoring").delete()

    def test_monitoring_initial_is_a_dependency_of_notifications_initial(self):
        self._simulate_inconsistent_history()

        with self.assertRaises(InconsistentMigrationHistory):
            call_command("migrate", database=PROBE_ALIAS, verbosity=0)

    def test_reset_repairs_an_inconsistent_history(self):
        self._simulate_inconsistent_history()

        call_command("reset_migrations", database=PROBE_ALIAS, yes=True, verbosity=0)

        applied = self.probe_migrations.applied_migrations()
        self.assertIn(("monitoring", "0001_initial"), applied)
        self.assertIn(("notifications", "0001_initial"), applied)
        self.assertIn(("analytics", "0001_initial"), applied)
        MigrationLoader(self.probe).check_consistent_history(self.probe)
        call_command("migrate", database=PROBE_ALIAS, verbosity=0)

    def test_reset_without_confirmation_drops_nothing(self):
        self._simulate_inconsistent_history()

        with self.assertRaisesMessage(CommandError, "Nothing was dropped"):
            call_command("reset_migrations", database=PROBE_ALIAS, verbosity=0)

        applied = self.probe_migrations.applied_migrations()
        self.assertNotIn(("monitoring", "0001_initial"), applied)
        self.assertIn(("notifications", "0001_initial"), applied)

    def test_reset_refuses_a_mismatched_confirmation(self):
        with self.assertRaisesMessage(CommandError, "Refusing to reset"):
            call_command(
                "reset_migrations",
                database=PROBE_ALIAS,
                yes=True,
                confirm_database="some-other-database",
                verbosity=0,
            )

    def test_reset_keeps_tables_no_django_model_claims(self):
        with self.probe.cursor() as cursor:
            cursor.execute("CREATE TABLE legacy_ingest (id integer primary key)")

        call_command("reset_migrations", database=PROBE_ALIAS, yes=True, verbosity=0)

        tables = set(self.probe.introspection.table_names())
        self.assertIn("legacy_ingest", tables)
        self.assertIn("django_migrations", tables)
        self.assertIn("monitoring_project", tables)

    def test_include_unmanaged_drops_those_tables_too(self):
        with self.probe.cursor() as cursor:
            cursor.execute("CREATE TABLE legacy_ingest (id integer primary key)")

        call_command(
            "reset_migrations",
            database=PROBE_ALIAS,
            yes=True,
            include_unmanaged=True,
            verbosity=0,
        )

        tables = set(self.probe.introspection.table_names())
        self.assertNotIn("legacy_ingest", tables)
        self.assertIn("monitoring_project", tables)
