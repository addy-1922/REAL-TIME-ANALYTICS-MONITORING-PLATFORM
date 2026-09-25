# Render migration history recovery

This document describes the **one-time** recovery for the current `signalwatch-db`
managed PostgreSQL instance, whose recorded migration history is inconsistent.

The recovery is opt-in. It runs only when `RESET_RENDER_DATABASE=true` is set on
the Render web service **and** the database is found to be in the exact
inconsistent state described below. A normal deploy never resets anything.

## Why the migration error occurs

`migrate` stops with:

```text
django.db.migrations.exceptions.InconsistentMigrationHistory:
Migration notifications.0001_initial is applied before its dependency
monitoring.0001_initial on database 'default'.
```

The migration files are correct and must not be changed.
`notifications/migrations/0001_initial.py` declares

```python
dependencies = [
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ("monitoring", "0001_initial"),
]
```

because `Notification.project` is a `ForeignKey` to `monitoring.Project`
(`to="monitoring.project"`), so the `monitoring` tables have to exist first.
`analytics/migrations/0001_initial.py` declares the same dependency for the same
reason. The order `migrate` always follows is:

```text
accounts.0001_initial
monitoring.0001_initial
analytics.0001_initial
notifications.0001_initial
```

The failure is therefore a **database state** problem: `django_migrations` in the
Render database contains rows for `notifications.0001_initial` and
`analytics.0001_initial` but not for `monitoring.0001_initial`. No `migrate` run
can repair that, because Django refuses to act on an inconsistent history.
Deleting, rewriting, reordering, or faking a migration is the wrong fix.

## What `RESET_RENDER_DATABASE=true` does

The web service environment variable switches on one command, run by
`docker-entrypoint.sh` before the normal migration step. That command is
`python manage.py reset_render_database`, and it is guarded at four levels:

1. **Explicit confirmation.** Without `RESET_RENDER_DATABASE` set to `true`, the
   command prints a message and exits non-zero without touching anything. Any
   other value, including `false`, `1`, and `yes`, is refused.
2. **PostgreSQL only.** The command refuses to run against SQLite or any other
   backend, and it refuses to run under the test runner.
3. **State detection.** It reads `django_migrations` and looks for an applied
   migration whose declared dependency is not applied, which is exactly the
   reported condition, for example
   `notifications.0001_initial` applied before `monitoring.0001_initial`. If the
   history is consistent it reports that and resets nothing.
4. **No hidden state.** The reset is not performed from application code, from a
   `post_migrate` hook, or from any other path. Without the environment variable
   the entrypoint runs only `python manage.py migrate --noinput`.

When the guards pass, the command drops and recreates the PostgreSQL `public`
schema, re-applies every migration, and then re-reads `django_migrations` to
confirm the history is now consistent:

```sql
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO <the DATABASE_URL role>;
ALTER SCHEMA public OWNER TO <the DATABASE_URL role>;
```

The role name is read from the `DATABASE_URL` connection settings. No credential
and no Render hostname is stored in the project.

## Intended only for the new, empty database

This mechanism exists for one reason: the current `signalwatch-db` instance is a
new deployment database that holds no data worth keeping. It is not a general
maintenance tool.

> **Warning.** `DROP SCHEMA public CASCADE` permanently and irreversibly deletes
> every table, view, sequence, and all rows in the `public` schema of the
> connected database, including `django_migrations`. There is no undo. Users,
> projects, events, alerts, and notifications are lost. Run it once, only against
> the new empty database. Once the database holds data worth keeping, use a
> data-preserving repair instead and delete this mechanism.

Before enabling it, confirm the database is the new one:

```bash
python manage.py showmigrations
```

```sql
SELECT app, name FROM django_migrations ORDER BY app, name;
```

Expect `notifications` and `analytics` to be listed while `monitoring` is
missing, and no application data that matters.

Suspend `signalwatch-worker` and `signalwatch-beat` while the reset runs so no
process holds a lock on the schema. If the drop cannot take its lock within 30
seconds the command fails and asks you to suspend the services and retry.

## Procedure

1. Deploy this commit to Render.
2. In the Render dashboard, suspend `signalwatch-worker` and `signalwatch-beat`.
3. On `signalwatch-web`, add the environment variable below.
4. Redeploy or restart `signalwatch-web`.
5. Watch the deploy log.
6. Remove the environment variable, then resume the worker and Beat services.

The log of the recovery deploy looks like this:

```text
=== Running Django database migrations ===
=== RESET_RENDER_DATABASE=true: running one-time database recovery ===
Target database: alias=default name=signalwatch
Inconsistent migration history detected:
  - analytics.0001_initial is applied but its dependency monitoring.0001_initial is not
  - notifications.0001_initial is applied but its dependency monitoring.0001_initial is not
Resetting the public schema. 18 tables will be deleted.
THIS PERMANENTLY DELETES ALL DATA.
Applying accounts.0001_initial... OK
Applying monitoring.0001_initial... OK
Applying analytics.0001_initial... OK
Applying notifications.0001_initial... OK
Reset complete. 19 migrations applied in dependency order.
Remove RESET_RENDER_DATABASE from the Render environment when the recovery is
done. Normal deployments only run python manage.py migrate --noinput.
=== Starting Uvicorn ===
```

## Self-disabling

The recovery is a one-time action by construction, not by convention:

- It only fires when the environment variable is set, and the variable is not set
  anywhere in the repository.
- It only resets when the inconsistent history is actually present. After the
  first successful reset that state no longer exists, so any later restart,
  redeploy, crash, or scale event finds a consistent database and resets nothing,
  even if the variable were still configured.
- It runs before `migrate`, which is the same command the normal startup already
  runs, so a second `migrate` in the same entrypoint is a harmless no-op.

## After the successful deployment

Remove `RESET_RENDER_DATABASE` from the Render web service environment
variables. Resume `signalwatch-worker` and `signalwatch-beat`, then recreate the
first administrator, because the old rows went with the schema:

```bash
python manage.py createsuperuser
python manage.py seed_demo_data      # optional demo content
```

Verify afterwards:

```bash
python manage.py showmigrations      # every migration is [X]
python manage.py migrate --noinput   # "No migrations to apply."
```

```text
https://<web-host>/health/           # 200
```

From this point a normal deployment does nothing but run Django migrations:
`python manage.py migrate --noinput` in `docker-entrypoint.sh`, and
`preDeployCommand: python manage.py migrate --noinput` in `render.yaml`.

## Manual alternative

The same reset can be performed by hand from a `psql` session without the
environment variable, which is useful if you prefer to keep the startup path
untouched. See [`RENDER_DATABASE_RESET.md`](RENDER_DATABASE_RESET.md).
