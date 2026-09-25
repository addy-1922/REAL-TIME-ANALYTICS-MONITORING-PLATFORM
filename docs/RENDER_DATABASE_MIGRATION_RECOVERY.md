# Render migration history recovery

A **one-time, manual** recovery for the current `signalwatch-db` managed
PostgreSQL instance, whose recorded migration history is inconsistent.

The command documented here is never executed by the application. It is not
called from `docker-entrypoint.sh`, the `Dockerfile`, `render.yaml`, Celery, or
any view, so no restart, redeploy, or scale event can ever reach it. You run it
by hand, once, in a one-off shell.

## 1. Why the error occurs

`python manage.py migrate --noinput` stops with:

```text
django.db.migrations.exceptions.InconsistentMigrationHistory:
Migration notifications.0001_initial is applied before its dependency
monitoring.0001_initial on database 'default'.
```

The migration files are correct and must not be changed, reordered, or faked.
`notifications/migrations/0001_initial.py` declares

```python
dependencies = [
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ("monitoring", "0001_initial"),
]
```

because `Notification.project` is a `ForeignKey` to `monitoring.Project`
(`to="monitoring.project"`), so the `monitoring` tables must exist first.
`analytics/migrations/0001_initial.py` declares the same dependency for the same
reason. The order `migrate` always follows is:

```text
accounts.0001_initial
monitoring.0001_initial
analytics.0001_initial
notifications.0001_initial
```

The failure is therefore a **database state** problem, not a code problem: the
`django_migrations` table in the Render database records `notifications.0001_initial`
as applied while `monitoring.0001_initial` is not applied. Django refuses to act
on an inconsistent history, and no `migrate` run can repair it. The fix is to
clear the state and let the migrations apply from an empty database.

## 2. How to run the command

Suspend `signalwatch-worker` and `signalwatch-beat` first, so no process holds a
lock on the schema. Then open the **Render web service shell** and run:

```bash
RESET_RENDER_DATABASE=true python manage.py reset_render_migrations
```

On Windows PowerShell, or when the variable is already configured in Render:

```powershell
$env:RESET_RENDER_DATABASE = "true"
python manage.py reset_render_migrations
Remove-Item Env:RESET_RENDER_DATABASE
```

The command aborts, without changing anything, unless every one of these is
true:

1. The connection is PostgreSQL. SQLite and every other backend are refused.
2. `RESET_RENDER_DATABASE` is exactly `true`. Any other value, including
   `True`, `TRUE`, `1`, `yes`, and an unset variable, is refused.
3. The `django_migrations` table exists.
4. `notifications.0001_initial` is recorded as applied **and**
   `monitoring.0001_initial` is **not** applied.

If all four hold, it prints every table that is about to be deleted and then runs:

```sql
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO <the role from DATABASE_URL>;
ALTER SCHEMA public OWNER TO <the role from DATABASE_URL>;
```

The role name comes from the `DATABASE_URL` connection settings. No credential
and no Render hostname is stored in the project. If the schema is locked by
another process the command fails after 30 seconds and asks you to suspend the
services; the transaction is rolled back, so nothing is half-dropped.

## 3. Required environment variable

```text
RESET_RENDER_DATABASE=true
```

That is the only value that is accepted. The variable is not set anywhere in
this repository, and it is not required by any normal deployment.

## 4. Intended only for the new, empty Render database

This command exists for one reason: the current `signalwatch-db` instance is a
new deployment database that holds no data worth keeping. It is not a general
maintenance tool and it is not a migration.

Confirm the database before you run it:

```bash
python manage.py showmigrations
```

```sql
SELECT app, name FROM django_migrations ORDER BY app, name;
```

Expect `notifications.0001_initial` to be listed while `monitoring.0001_initial`
is missing. The command verifies this itself and aborts if it is not exactly the
case.

## 5. It permanently deletes all data in the public schema

> **Warning.** `DROP SCHEMA public CASCADE` permanently and irreversibly deletes
> every table, view, and sequence in the `public` schema of the connected
> database, together with all rows in them, including the `django_migrations`
> records. There is no undo. Users, projects, events, alert rules, triggers, and
> notifications are all lost.
>
> Run it once, only against the new, empty database. Once that database holds
> data worth keeping, use a data-preserving repair instead and do not run this
> command again.

## 6. After the reset, run the migrations

The command deliberately does not migrate. With the schema empty, run:

```bash
python manage.py migrate --noinput
```

Every migration is then applied in dependency order, `monitoring.0001_initial`
before `analytics.0001_initial` and `notifications.0001_initial`. The
application does not need to be restarted for this; the next deploy runs the
same command through `docker-entrypoint.sh`.

Verify:

```bash
python manage.py showmigrations      # every migration is [X]
python manage.py migrate --noinput   # "No migrations to apply."
```

```text
https://<web-host>/health/           # 200
```

Recreate the first administrator, because the old rows went with the schema:

```bash
python manage.py createsuperuser
python manage.py seed_demo_data      # optional demo content
```

## 7. Remove `RESET_RENDER_DATABASE` afterwards

If you passed the variable inline on the command line, nothing is left to clean
up. If you set it in Render, delete it from the **signalwatch-web** service
environment variables once the reset and the migration have succeeded, then
resume `signalwatch-worker` and `signalwatch-beat`.

After that, deployments do nothing but run Django migrations:

- `docker-entrypoint.sh`: `python manage.py migrate --noinput`, then Uvicorn.
- `render.yaml`: `preDeployCommand: python manage.py migrate --noinput`.

## Manual alternative

The same reset can be typed directly into a `psql` session without the command.
See [`RENDER_DATABASE_RESET.md`](RENDER_DATABASE_RESET.md).
