"""One-time manual recovery for the new Render PostgreSQL database.

This command is never called by the application. It is not referenced by
``docker-entrypoint.sh``, the ``Dockerfile``, ``render.yaml``, Celery, or any
view, so a restart, redeploy, or scale event cannot reach it. It is run by hand
exactly once, from a one-off shell, when the Render database holds no data worth
keeping and its recorded migration history is inconsistent.

The command refuses to do anything unless all of the following hold:

* the connection is PostgreSQL;
* ``RESET_RENDER_DATABASE`` is set to exactly ``true``;
* ``django_migrations`` records ``notifications.0001_initial`` as applied while
  ``monitoring.0001_initial`` is not applied.

It drops and recreates the ``public`` schema and nothing else. It does not run
``migrate``; the operator runs ``python manage.py migrate --noinput`` afterwards,
which then applies every migration in dependency order from an empty database.
"""

import os
import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections, transaction
from django.db.migrations.recorder import MigrationRecorder

CONFIRMATION_ENV_VAR = "RESET_RENDER_DATABASE"
CONFIRMATION_VALUE = "true"
REQUIRED_VENDOR = "postgresql"
INCONSISTENT_MIGRATION = ("notifications", "0001_initial")
MISSING_DEPENDENCY = ("monitoring", "0001_initial")
LOCK_TIMEOUT = "30s"


def running_under_test_runner():
    """Return True when the process was started by ``manage.py test``."""
    return len(sys.argv) > 1 and sys.argv[1] == "test"


class Command(BaseCommand):
    help = (
        "One-time manual recovery for the new, empty Render PostgreSQL database. "
        "Requires RESET_RENDER_DATABASE=true and only acts when "
        f"{INCONSISTENT_MIGRATION[0]}.{INCONSISTENT_MIGRATION[1]} is applied "
        f"while {MISSING_DEPENDENCY[0]}.{MISSING_DEPENDENCY[1]} is not applied, "
        "in which case it drops and recreates the public schema. Run "
        "'python manage.py migrate --noinput' afterwards."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default="default",
            help="Database alias to inspect and reset. Default: default.",
        )

    def handle(self, *args, **options):
        self._require_confirmation()

        alias = options["database"]
        connection = connections[alias]
        if connection.vendor != REQUIRED_VENDOR:
            raise CommandError(
                f"Refusing to reset a {connection.vendor} database. This recovery "
                f"only supports {REQUIRED_VENDOR}."
            )
        if running_under_test_runner():
            raise CommandError("Refusing to reset a database from the test runner.")

        settings = connection.settings_dict
        self.stdout.write(f"Target database: alias={alias} name={settings['NAME']}")
        self.stdout.write(f"Host: {settings.get('HOST')}:{settings.get('PORT', 5432)}")

        recorder = MigrationRecorder(connection)
        if not recorder.has_table():
            raise CommandError(
                "The django_migrations table does not exist, so no migration is "
                "recorded as applied and the required inconsistent state cannot be "
                "present. Nothing was changed. Run 'python manage.py migrate "
                "--noinput' instead."
            )

        applied = set(recorder.applied_migrations())
        self._require_inconsistent_state(applied)

        self._warn_about_deletion(connection, applied)
        self._reset_public_schema(connection, alias)

        self.stdout.write(
            self.style.SUCCESS(
                "The public schema was dropped and recreated. The database is now "
                "empty."
            )
        )
        self.stdout.write("Next step, run this by hand:")
        self.stdout.write("    python manage.py migrate --noinput")
        self.stdout.write(
            f"Then remove {CONFIRMATION_ENV_VAR} from the Render environment."
        )

    def _require_confirmation(self):
        raw = os.environ.get(CONFIRMATION_ENV_VAR)
        value = "" if raw is None else raw.strip()
        if value != CONFIRMATION_VALUE:
            raise CommandError(
                f"{CONFIRMATION_ENV_VAR} is not set to "
                f"\"{CONFIRMATION_VALUE}\" (current value: {raw!r}). Nothing was "
                "changed. This command refuses to touch the database without that "
                f"explicit confirmation. Set {CONFIRMATION_ENV_VAR}="
                f"{CONFIRMATION_VALUE} in the one-off shell that runs it, and "
                "remove it again afterwards."
            )

    def _require_inconsistent_state(self, applied):
        applied_label = "{0}.{1}".format(*INCONSISTENT_MIGRATION)
        dependency_label = "{0}.{1}".format(*MISSING_DEPENDENCY)
        if INCONSISTENT_MIGRATION not in applied:
            raise CommandError(
                f"{applied_label} is not recorded as applied, so the database is "
                "not in the expected inconsistent state. Nothing was changed. "
                "Investigate the reported migration error before resetting anything."
            )
        if MISSING_DEPENDENCY in applied:
            raise CommandError(
                f"{dependency_label} is already applied, so the database is not in "
                "the expected inconsistent state. Nothing was changed. "
                "'python manage.py migrate --noinput' is the correct next step."
            )
        self.stdout.write(
            f"Inconsistent state confirmed: {applied_label} is applied and "
            f"{dependency_label} is not."
        )

    def _warn_about_deletion(self, connection, applied):
        with connection.cursor() as cursor:
            existing = connection.introspection.table_names(cursor)
        recorded = len(applied)
        warning = (
            "WARNING: this permanently deletes the PostgreSQL public schema of "
            f"{connection.settings_dict['NAME']}.\n"
            f"  {len(existing)} tables, all rows in them, and all {recorded} "
            "django_migrations records will be destroyed.\n"
            "  There is no undo. Use it only on the new, empty Render database that "
            "holds no data worth keeping."
        )
        self.stdout.write(self.style.WARNING(warning))
        for table in existing:
            self.stdout.write(f"  - {table}")

    def _reset_public_schema(self, connection, alias):
        quote_name = connection.ops.quote_name
        app_user = (connection.settings_dict.get("USER") or "").strip()
        statements = ["DROP SCHEMA public CASCADE", "CREATE SCHEMA public"]
        if app_user:
            statements.append(f"GRANT ALL ON SCHEMA public TO {quote_name(app_user)}")
            statements.append(f"ALTER SCHEMA public OWNER TO {quote_name(app_user)}")

        try:
            with transaction.atomic(using=alias):
                with connection.cursor() as cursor:
                    cursor.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
                    for statement in statements:
                        self.stdout.write(f"    {statement}")
                        cursor.execute(statement)
        except DatabaseError as exc:
            raise CommandError(
                f"Schema reset failed: {exc}. Nothing was changed. If the worker "
                "or Beat service is running, suspend every Render service and run "
                "the command again."
            ) from exc

        with connection.cursor() as cursor:
            remaining = connection.introspection.table_names(cursor)
        if remaining:
            raise CommandError(f"Schema reset did not clear the database: {remaining}.")
