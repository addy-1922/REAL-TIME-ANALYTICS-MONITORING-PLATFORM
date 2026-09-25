# One-time Render PostgreSQL database reset

This is a **manual, one-time operator procedure** for the current `signalwatch-db`
managed PostgreSQL instance. It is documented, not automated: nothing in this
repository performs it, so a restart, redeploy, or scale event can never destroy
the database.

For the same reset performed by the opt-in `reset_render_database` management
command, see [`RENDER_DATABASE_MIGRATION_RECOVERY.md`](RENDER_DATABASE_MIGRATION_RECOVERY.md).
That command is gated on `RESET_RENDER_DATABASE=true` and on the database
actually being in the inconsistent state; this document covers doing it by hand
from `psql` instead.

## 1. Why this is needed

The current deployment fails at the migration step in `docker-entrypoint.sh`:

```text
=== Running Django database migrations ===
django.db.migrations.exceptions.InconsistentMigrationHistory:
Migration notifications.0001_initial is applied before its dependency
monitoring.0001_initial on database 'default'.
```

The migration files are correct. `notifications/migrations/0001_initial.py`
declares

```python
dependencies = [
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ("monitoring", "0001_initial"),
]
```

because `Notification.project` is a `ForeignKey` to `monitoring.Project`
(`to="monitoring.project"`, `notifications/migrations/0001_initial.py`), so the
`monitoring` tables have to exist first. `analytics/migrations/0001_initial.py`
declares the same dependency for the same reason. `migrate` therefore always
applies them in this order:

```text
accounts.0001_initial
monitoring.0001_initial
analytics.0001_initial
notifications.0001_initial
```

The error is purely a **database state** problem. The `django_migrations` table
in the Render database contains a row for `notifications.0001_initial` but not
for `monitoring.0001_initial`, which no `migrate` run can ever repair. Django
refuses to do anything until the state is consistent.

The `signalwatch-db` instance is a new deployment database with no data that
needs to be preserved, so the correct fix is to remove the schema and let Django
rebuild it from zero. Do **not** edit, reorder, delete, or fake a migration.

## 2. Warning

> `DROP SCHEMA public CASCADE` **permanently and irreversibly deletes every
> table, view, sequence, and all rows in the `public` schema of the connected
> database.** There is no undo and no Render backup snapshot is assumed. It also
> deletes `django_migrations`, so every migration is re-applied from scratch and
> all users, projects, events, alerts, and notifications are lost.
>
> Run it only against the new `signalwatch` database, only after confirming the
> database is the new one, and only once. If that database ever holds data worth
> keeping, use a data-preserving repair instead.

## 3. Confirm the target is the new, empty database

Suspend the services so no process holds a connection or lock while the schema is
being replaced: Render dashboard, suspend `signalwatch-web`,
`signalwatch-worker`, and `signalwatch-beat`.

Then connect and confirm the identity of the database before changing anything.
The connection string is the `DATABASE_URL` of any service, or
`databases` → `signalwatch-db` → **Connection** in the Render dashboard. The
Blueprint values are database `signalwatch`, user `signalwatch`
(`render.yaml`).

Run this in `psql` as the same `signalwatch` role the application uses:

```sql
SELECT current_database(), current_user, version();

-- The schema currently holds the inconsistent state. Expect notification tables
-- and a django_migrations row for notifications.0001_initial.
\dt public.*

SELECT app, name FROM django_migrations ORDER BY app, name;
```

You are looking at the right database when all of the following hold:

- `current_database()` returns `signalwatch`.
- The tables are the ones this project creates (`monitoring_project`,
  `notifications_notification`, `analytics_dailyanalyticssummary`,
  `accounts_profile`, `auth_user`, `django_migrations`), with no unexpected
  application data.
- The `django_migrations` rows show `notifications` applied while `monitoring`
  is missing.
- You accept that every row in this database will be deleted.

## 4. Drop and recreate the schema

Connect with the **application** role, `signalwatch`, so the recreated schema is
owned by that role and the app can keep using it:

```bash
psql "postgresql://signalwatch:<password>@<host>:5432/signalwatch"
```

Then run exactly:

```sql
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO signalwatch;
```

The two `DROP`/`CREATE` statements are the reset. `DROP SCHEMA public CASCADE`
removes every object in the schema, including `django_migrations`;
`CREATE SCHEMA public` gives the application an empty schema owned by the
connecting role. The `GRANT` is harmless when the role already owns the schema
and covers a connection made with a different, privileged role.

Verify the schema is empty before continuing:

```sql
\dn
\dt public.*
```

`\dt` should report "did not find any relations".

If you connected as a superuser instead, fix the ownership so the app role keeps
working:

```sql
ALTER SCHEMA public OWNER TO signalwatch;
```

## 5. Redeploy the Render web service

Nothing in the application has to change. Resume `signalwatch-worker` and
`signalwatch-beat`, then trigger a deploy of `signalwatch-web` from the Render
dashboard, or push a commit. On a Blueprint deploy the `preDeployCommand` runs
first; with the Docker image the container entrypoint runs instead. Both are the
same single command, `docker-entrypoint.sh` line 12:

```bash
python manage.py migrate --noinput
```

which is followed by Uvicorn in the same script. Django now sees an empty
`django_migrations` table and applies every migration in dependency order.

## 6. Verify migrations applied in dependency order

In the deploy log, the `Applying ...` lines must appear with `monitoring` before
`analytics` and `notifications`, and no `InconsistentMigrationHistory`:

```text
=== Running Django database migrations ===
Operations to perform:
  Apply all migrations: accounts, admin, analytics, auth, contenttypes, monitoring, notifications, sessions
Applying accounts.0001_initial... OK
Applying monitoring.0001_initial... OK
Applying analytics.0001_initial... OK
Applying notifications.0001_initial... OK
...
=== Starting Uvicorn ===
```

Confirm the same from the Render web service shell:

```bash
python manage.py showmigrations
```

Every migration must be `[X]`, in particular:

```text
monitoring
 [X] 0001_initial
analytics
 [X] 0001_initial
notifications
 [X] 0001_initial
```

A clean read of the recorder:

```sql
SELECT app, COUNT(*) FROM django_migrations GROUP BY app ORDER BY app;
```

and a no-op migration, which must report `No migrations to apply`:

```bash
python manage.py migrate --noinput
```

## 7. Verify the application starts

In the deploy log, the final lines must be the Uvicorn startup, with the Render
`PORT`:

```text
=== Starting Uvicorn ===
INFO:     Uvicorn running on http://0.0.0.0:10000 (Press CTRL+C to quit)
```

Then check the health endpoint and the login page:

```bash
curl -i https://<web-host>/health/
curl -I https://<web-host>/accounts/login/
```

`/health/` must return `200`. Recreate the first administrator, because the old
rows went with the schema:

```bash
python manage.py createsuperuser
python manage.py seed_demo_data      # optional demo content
```

## 8. After the reset

The database is now consistent and self-maintaining. The normal deployment path
is unchanged and needs no further intervention:

- `render.yaml` keeps `preDeployCommand: python manage.py migrate --noinput`.
- `docker-entrypoint.sh` keeps `python manage.py migrate --noinput` followed by
  `exec python -m uvicorn config.asgi:application ...`.
- No custom reset command was added to the project, and no destructive SQL was
  added to the entrypoint, the Dockerfile, or any startup path.

This procedure is finished. Do not repeat it.
