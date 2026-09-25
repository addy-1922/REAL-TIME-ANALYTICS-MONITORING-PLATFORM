"""One-time, explicitly enabled recovery for the new Render PostgreSQL database.

``docker-entrypoint.sh`` calls this command only when
``RESET_RENDER_DATABASE=true`` is set as an environment variable in Render, and
even then the command resets the schema only when it finds an applied migration
whose declared dependency is not applied, for example
``notifications.0001_initial`` applied before ``monitoring.0001_initial``.

That makes the recovery self-disabling: once the schema has been reset and the
migrations have been applied, the inconsistent state is gone, so every later
restart or redeploy is a no-op even if the variable is still configured.

Nothing else in the project runs this command. Normal startup is unchanged and
runs ``python manage.py migrate --noinput`` only.
"""

import os
import sys

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

CONFIRMATION_ENV_VAR = "RESET_RENDER_DATABASE"
CONFIRMATION_VALUE = "true"
REQUIRED_VENDOR = "postgresql"
LOCK_TIMEOUT = "30s"


def find_inconsistent_migrations(connection):
    """Return every ``(applied_migration, missing_dependency)`` pair in a database.

    This mirrors ``MigrationLoader.check_consistent_history`` but collects the
    offending pairs instead of raising, so the caller can report them and decide
    what to do. Squashed replacements and migrations unknown to the project are
    ignored exactly as Django ignores them.
    """
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    applied = set(loader.applied_migrations)
    inconsistent = []
    for migration in sorted(applied):
        if migration not in loader.graph.nodes:
            continue
        for parent in loader.graph.node_map[migration].parents:
            if parent in applied:
                continue
            replacement = loader.replacements.get(parent)
            if replacement and any(
                replaced in applied for replaced in replacement.replaces
            ):
                continue
            inconsistent.append((migration, parent))
    return inconsistent


def running_under_test_runner():
    """Return True when the process was started by ``manage.py test``."""
    return len(sys.argv) > 1 and sys.argv[1] == "test"


class Command(BaseCommand):
    help = (
        "One-time recovery for the new Render PostgreSQL database: drop and "
        "recreate the public schema and re-apply every migration, but only when "
        f"{CONFIRMATION_ENV_VAR}={CONFIRMATION_VALUE} is set and only when the "
        "recorded migration history is actually inconsistent."
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

        inconsistent = find_inconsistent_migrations(connection)
        if not inconsistent:
            self.stdout.write(
                self.style.SUCCESS(
                    "No inconsistent migration history found. Nothing was reset."
                )
            )
            self._print_reminder()
            return

        self.stdout.write(
            self.style.WARNING("Inconsistent migration history detected:")
        )
        for migration, parent in inconsistent:
            self.stdout.write(
                f"  - {migration[0]}.{migration[1]} is applied but its dependency "
                f"{parent[0]}.{parent[1]} is not"
            )

        self._reset_schema(connection, alias)
        self.stdout.write("Applying every migration in dependency order ...")
        call_command(
            "migrate", database=alias, interactive=False, verbosity=options["verbosity"]
        )

        remaining = find_inconsistent_migrations(connection)
        if remaining:
            raise CommandError(
                "The reset finished but the migration history is still "
                f"inconsistent: {remaining}."
            )
        applied = sorted(
            f"{app}.{name}"
            for app, name in MigrationRecorder(connection).applied_migrations()
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Reset complete. {len(applied)} migrations applied in dependency "
                "order."
            )
        )
        self._print_reminder()

    def _require_confirmation(self):
        raw = os.environ.get(CONFIRMATION_ENV_VAR)
        value = "" if raw is None else raw.strip().lower()
        if value != CONFIRMATION_VALUE:
            raise CommandError(
                f"{CONFIRMATION_ENV_VAR} is not set to "
                f"\"{CONFIRMATION_VALUE}\" (current value: {raw!r}). This command "
                "refuses to touch the database without that explicit confirmation. "
                f"Set {CONFIRMATION_ENV_VAR}={CONFIRMATION_VALUE} in the Render "
                "web service environment only for the one-time recovery of the new, "
                "empty database, and remove it again afterwards."
            )

    def _reset_schema(self, connection, alias):
        quote_name = connection.ops.quote_name
        app_user = (connection.settings_dict.get("USER") or "").strip()
        statements = ["DROP SCHEMA public CASCADE", "CREATE SCHEMA public"]
        if app_user:
            statements.append(
                f"GRANT ALL ON SCHEMA public TO {quote_name(app_user)}"
            )
            statements.append(
                f"ALTER SCHEMA public OWNER TO {quote_name(app_user)}"
            )

        with connection.cursor() as cursor:
            existing = connection.introspection.table_names(cursor)
        self.stdout.write(
            f"Resetting the public schema. {len(existing)} tables will be deleted."
        )
        self.stdout.write(self.style.WARNING("THIS PERMANENTLY DELETES ALL DATA."))

        try:
            with transaction.atomic(using=alias):
                with connection.cursor() as cursor:
                    cursor.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
                    for statement in statements:
                        cursor.execute(statement)
        except DatabaseError as exc:
            raise CommandError(
                f"Schema reset failed: {exc}. If the worker or Beat service is "
                "still running, suspend every Render service and run the reset "
                "again."
            ) from exc

        with connection.cursor() as cursor:
            remaining = connection.introspection.table_names(cursor)
        if remaining:
            raise CommandError(
                f"Schema reset did not clear the database: {remaining}."
            )

    def _print_reminder(self):
        self.stdout.write(
            f"Remove {CONFIRMATION_ENV_VAR} from the Render environment when the "
            "recovery is done. Normal deployments only run "
            "python manage.py migrate --noinput."
        )
