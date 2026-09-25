"""One-time recovery command for a database with inconsistent migration state.

This command is deliberately manual and opt-in. It is never called by the
Docker entrypoint, ``render.yaml``, Celery, or any application code, so a
restart or a redeploy can never destroy a database on its own. Run it by hand
from a one-off shell only when a database holds no data worth keeping and its
``django_migrations`` rows disagree with the migration graph, for example::

    InconsistentMigrationHistory: Migration notifications.0001_initial is
    applied before its dependency monitoring.0001_initial on database 'default'.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django.db.utils import ConnectionDoesNotExist

LOCK_TIMEOUT = "10s"
SUPPORTED_VENDORS = {"postgresql", "sqlite"}


class Command(BaseCommand):
    help = (
        "Destructive one-time recovery: drop every Django table in the target "
        "database and re-apply all migrations from scratch. Use it only on a new "
        "deployment database with no data to preserve."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Required confirmation. Without this flag nothing is dropped.",
        )
        parser.add_argument(
            "--database",
            default="default",
            help="Database alias to reset. Default: default.",
        )
        parser.add_argument(
            "--confirm-database",
            default="",
            help=(
                "Abort unless the target database name matches this value exactly. "
                "Recommended for a managed database."
            ),
        )
        parser.add_argument(
            "--include-unmanaged",
            action="store_true",
            help=(
                "Also drop tables that no current Django model claims, such as "
                "leftovers from a removed app. They are only reported by default."
            ),
        )
        parser.add_argument(
            "--skip-migrate",
            action="store_true",
            help="Drop the tables without running migrate afterwards.",
        )

    def handle(self, *args, **options):
        alias = options["database"]
        try:
            connection = connections[alias]
        except ConnectionDoesNotExist as exc:
            raise CommandError(f"Unknown database alias {alias!r}.") from exc

        if connection.vendor not in SUPPORTED_VENDORS:
            raise CommandError(
                f"Refusing to reset a {connection.vendor} database. This command "
                f"supports {', '.join(sorted(SUPPORTED_VENDORS))} only."
            )

        database_name = connection.settings_dict["NAME"]
        self.stdout.write(f"Target database: alias={alias} name={database_name}")
        if connection.vendor == "postgresql":
            self.stdout.write(
                f"PostgreSQL host: {connection.settings_dict.get('HOST')}"
            )

        expected = options["confirm_database"]
        if expected and expected != database_name:
            raise CommandError(
                f"Refusing to reset {database_name!r}: --confirm-database expected "
                f"{expected!r}."
            )

        with connection.cursor() as cursor:
            existing = set(connection.introspection.table_names(cursor))
        django_tables = set(
            connection.introspection.django_table_names(
                only_existing=True, include_views=False
            )
        )

        recorder = MigrationRecorder(connection)
        django_tables.add(recorder.Migration._meta.db_table)
        drop = sorted(table for table in django_tables if table in existing)
        leftovers = sorted(existing - set(drop))

        if not drop:
            raise CommandError(
                f"No Django tables found in {database_name!r}. There is nothing to "
                "reset; check DATABASE_URL if this is unexpected."
            )

        if leftovers:
            self.stdout.write(
                self.style.WARNING(
                    "Tables not claimed by any Django model (left in place unless "
                    "--include-unmanaged is used):"
                )
            )
            for table in leftovers:
                self.stdout.write(f"  - {table}")
            if options["include_unmanaged"]:
                drop = sorted(set(drop) | set(leftovers))
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "If any of these is a stale application table that blocks "
                        "migrate, re-run with --include-unmanaged."
                    )
                )

        self.stdout.write(self.style.WARNING("These tables will be dropped:"))
        for table in drop:
            self.stdout.write(f"  - {table}")

        if not options["yes"]:
            raise CommandError(
                "Nothing was dropped. Read the list above, then re-run with --yes to "
                "perform the reset."
            )

        self._drop_tables(connection, alias, drop)
        self.stdout.write(self.style.SUCCESS(f"Dropped {len(drop)} tables."))

        if options["skip_migrate"]:
            self.stdout.write(
                self.style.WARNING(
                    "Skipping migrate (--skip-migrate). Run "
                    f"'python manage.py migrate --noinput --database={alias}' to "
                    "apply the migrations in dependency order."
                )
            )
            return

        self.stdout.write("Applying every migration in dependency order ...")
        call_command(
            "migrate",
            database=alias,
            interactive=False,
            verbosity=options["verbosity"],
        )

        MigrationLoader(connection, ignore_no_migrations=True).check_consistent_history(
            connection
        )
        applied = sorted(
            f"{app}.{name}"
            for app, name in MigrationRecorder(connection).applied_migrations()
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Migration history is consistent: {len(applied)} migrations applied."
            )
        )
        for name in applied:
            self.stdout.write(f"  - {name}")

    def _drop_tables(self, connection, alias, tables):
        quote_name = connection.ops.quote_name
        cascade = " CASCADE" if connection.vendor == "postgresql" else ""
        try:
            with transaction.atomic(using=alias):
                with connection.cursor() as cursor:
                    if connection.vendor == "postgresql":
                        cursor.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
                    for table in tables:
                        cursor.execute(
                            f"DROP TABLE IF EXISTS {quote_name(table)}{cascade}"
                        )
        except DatabaseError as exc:
            raise CommandError(
                f"Dropping tables failed: {exc}. If a service is still serving "
                "traffic, stop the web, worker, and Beat services and try again."
            ) from exc
