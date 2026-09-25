# SignalWatch

SignalWatch is a Django 5.2 monitoring and analytics application for authenticated users who own projects, ingest application events, inspect errors and slow requests, configure alert rules, and receive notifications. This document describes the code and deployment files in this exact checkout.

## Verification status

This checkout has been executed and verified. The following commands were run successfully against the source in this repository:

| Check | Command | Result |
| --- | --- | --- |
| Django system check | `python manage.py check` | `System check identified no issues (0 silenced).` |
| Migration drift | `python manage.py makemigrations --check --dry-run` | `No changes detected` |
| Deployment check | `python manage.py check --deploy` with `DEBUG=False` | Clean apart from the placeholder secret used for the check |
| OpenAPI schema | `python manage.py spectacular --file schema.yml` | Generated with no warnings |
| Test suite | `python manage.py test tests --settings=config.settings_test` | `Ran 114 tests ... OK` |
| Demo data | `python manage.py seed_demo_data` | Seeded 2 projects, 420 events, alert rules, triggers and notifications |

Both defects that earlier revisions of this document described as blocking are fixed: `django-redis` is now a pinned dependency in `requirements.txt`, and the `intcomma` filter is provided by the project template library `dashboard/templatetags/dashboard_tags.py`, which the affected templates load.

The Docker Compose stack could not be executed in this environment because no Docker daemon is available, so the container instructions below are written from the source files rather than from a run.

## Overview and implemented features

The repository contains code for:

- Registration, login, logout, password changes, password resets, and user profiles with optional avatar images.
- User-owned projects with a SHA-256 API-key hash and a display prefix.
- One-time plaintext API-key display when a project is created or its key is regenerated.
- Event ingestion with event type, message, service, environment, response time, status code, JSON metadata, client IP, and creation time.
- Project dashboards, event lists and detail pages, alert-rule forms, activity history, and filtered CSV export.
- Cross-project analytics, error monitoring, slow-request views, response-time summaries, and daily summary models.
- Django REST Framework resources, session-authenticated reads, API-key event writes, filtering, ordering, pagination, and an OpenAPI schema.
- Authenticated Channels WebSocket consumers for project events and user notifications.
- Celery tasks for post-commit alert evaluation, daily summaries, daily email reports, error-spike detection, and event-retention cleanup.
- Notification history, read state, unread counts, and an email task.
- Django admin registration for the implemented models.
- A `seed_demo_data` management command that generates a realistic demo dataset.
- An automated test suite covering models, ownership boundaries, API authentication and ingestion, analytics services, Celery tasks, and WebSocket consumers.

## Error and success semantics

A single definition is used everywhere: server-side queries, the rendered dashboards, the Celery alert rules, and the browser JavaScript.

- An event is an **error** when `status_code >= 400` or when `event_type` is `APPLICATION_ERROR` or `DATABASE_ERROR`.
- An event is a **success** when `200 <= status_code < 400` and it is not an error by the rule above.

`analytics.services.error_q()` and `success_q()` are the canonical implementations, and `monitoring.Event.is_error` / `is_success` mirror them.


## Architecture

```text
Browser / API client
        |
        | HTTPS + session cookie or X-API-Key
        v
Uvicorn -> Django ASGI -> Django views / DRF
        |                       |
        |                       +-> PostgreSQL: users, projects, events,
        |                           alerts, notifications, summaries
        |
        +-> Redis
        |    +-> Django cache
        |    +-> Channels group transport
        |    +-> Celery broker and result backend
        |
        +-> Celery worker -> database and optional SMTP
        |
        +-> Celery Beat -> scheduled task queue
```

- `config.asgi.application` routes HTTP through Django and WebSockets through `AllowedHostsOriginValidator` plus session authentication.
- `REDIS_URL` selects the `channels_redis` channel layer and the `django_redis` cache backend; an empty value selects the local-memory cache and channel-layer fallbacks. The `django-redis` distribution is pinned in `requirements.txt`.
- Celery uses `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND`; each falls back to the value of `REDIS_URL` and then to in-memory transports.
- WhiteNoise serves collected static files. Static files are collected into `staticfiles/`; uploaded media remains under `media/`.
- Scheduled task times use UTC: daily summaries at 00:15, daily reports at 07:00, error-spike detection every five minutes, and event cleanup at 02:30.

## Stack

- Python 3.12
- Django 5.2.5
- Django REST Framework 3.16.1
- django-filter 25.1
- Channels 4.3.1 and channels-redis 4.3.0
- Celery 5.5.3 with Redis 6.4.0
- PostgreSQL through psycopg 3.2.9
- Uvicorn 0.35.0 for ASGI and WebSockets
- WhiteNoise 6.9.0 for static files
- drf-spectacular 0.28.0 for `/api/schema/` and `/api/docs/`
- Pillow 11.3.0 for profile image validation
- Gunicorn 23.0.0 is installed but is not the command used by the supplied Docker or Render ASGI configuration

The checks in this document were executed with Python 3.13.9 and Django 5.2.17 on Windows, which is within the supported range for the pins above. The Docker image targets Python 3.12.

## Folder structure

```text
.
|-- accounts/                 Authentication and profile app
|-- analytics/                Analytics views, services, summaries, and tasks
|-- api/                      DRF serializers, views, auth, pagination, and schema URLs
|-- config/                   Django settings, URLs, WSGI, ASGI, and Celery app
|-- dashboard/                Root dashboard and health endpoint
|-- monitoring/               Projects, events, alert rules, activity, and tasks
|-- notifications/            Notification model, views, services, and tasks
|-- static/                   CSS, JavaScript, and image source directory
|-- templates/                Django templates
|-- tests/                   Automated test suite (114 tests) run under config.settings_test
|-- media/                    Persistent uploaded profile pictures
|-- manage.py                 Django management entry point
|-- requirements.txt          Pinned Python dependencies
|-- .env.example              Local environment template
|-- Dockerfile                Python 3.12 slim non-root image
|-- docker-compose.yml        Local PostgreSQL, Redis, migrations, web, worker, and beat
`-- render.yaml               Render blueprint
```

## URLs

Use `http://127.0.0.1:8000` for the local ASGI server and the public HTTPS origin for a deployed service. Replace `{project_id}`, `{event_id}`, `{notification_id}`, and `{alert_id}` with the numeric IDs returned by the application.

| URL | Purpose | Authentication |
| --- | --- | --- |
| `/` | Main dashboard | Login required |
| `/health/` | Lightweight HTTP health response | Public |
| `/accounts/login/` | Login | Public |
| `/accounts/logout/` | Logout | Login required, POST |
| `/accounts/register/` | Registration | Public |
| `/accounts/password/change/` | Change password | Login required |
| `/accounts/password/reset/` | Request a reset email | Public |
| `/accounts/profile/` | Profile | Login required |
| `/accounts/profile/edit/` | Edit profile and avatar | Login required |
| `/projects/` | Project list | Login required |
| `/projects/new/` | Create a project | Login required |
| `/projects/{project_id}/` | Project details and one-time key display | Login required, owner only |
| `/projects/{project_id}/dashboard/` | Per-project metrics | Login required, owner only |
| `/projects/{project_id}/events/` | Event list and filters | Login required, owner only |
| `/projects/{project_id}/events/{event_id}/` | Event detail | Login required, owner only |
| `/projects/{project_id}/events/export/` | Filtered CSV export | Login required, owner only |
| `/projects/{project_id}/alerts/` | Alert-rule list | Login required, owner only |
| `/projects/{project_id}/alerts/new/` | Create an alert rule | Login required, owner only |
| `/projects/{project_id}/alerts/{alert_id}/toggle/` | Toggle an alert rule | Login required, POST, owner only |
| `/projects/activity/` | User activity history | Login required |
| `/analytics/` | Analytics overview | Login required |
| `/analytics/errors/` | Error monitoring | Login required |
| `/analytics/errors/{event_id}/` | Analytics error detail | Login required, owner only |
| `/analytics/slow-requests/` | Requests at or above the configured threshold | Login required |
| `/notifications/` | Notification history | Login required |
| `/notifications/mark-read/{notification_id}/` | Mark one notification read | Login required, POST |
| `/notifications/mark-all-read/` | Mark all notifications read | Login required, POST |
| `/api/events/` | Session-authenticated event list or API-key event creation | Read: session; create: API key |
| `/api/projects/` | Session-authenticated project list/create | Login required |
| `/api/projects/{project_id}/` | Session-authenticated project detail | Login required, owner only |
| `/api/analytics/` | Session-authenticated aggregate analytics | Login required |
| `/api/alerts/` | Session-authenticated alert list/create | Login required |
| `/api/notifications/` | Session-authenticated notification list | Login required |
| `/api/notifications/{notification_id}/read/` | Mark a notification read | Login required, POST |
| `/api/schema/` | OpenAPI schema | Public |
| `/api/docs/` | Swagger UI | Public documentation; resource calls still require their normal auth |
| `/api-auth/` | DRF session login/logout helper | Public login page |

## Windows PowerShell development setup

Prerequisites:

- Python 3.12 for Windows
- PostgreSQL when not using SQLite
- Docker Desktop when using containerized PostgreSQL/Redis or Docker Compose
- A terminal that supports PowerShell commands

Open PowerShell and run:

```powershell
Set-Location "C:\Users\hp\Desktop\Real time analytics platform"
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks `Activate.ps1`, enable scripts for the current process only and retry. This does not change the machine or user execution policy:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Confirm the interpreter:

```powershell
python --version
python -c "import sys; print(sys.executable)"
```

Deactivate when finished:

```powershell
deactivate
```

If execution policy is managed by an organization, use the non-activating form instead:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

### Create the environment file

```powershell
Copy-Item .env.example .env
```

Generate a Django secret without hardcoding one:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Copy that generated value into the empty `SECRET_KEY` line in `.env`, then remove it from the terminal history if desired. Do not commit `.env`.

### SQLite fallback

SQLite is selected only when `DB_NAME`, `DB_USER`, and `DB_HOST` are all empty. In that configuration, Django uses `db.sqlite3` in the project root.

```dotenv
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=5432
```

Apply migrations and create an administrator:

```powershell
python manage.py migrate
python manage.py createsuperuser
```

SQLite is useful for a single local process. It is not the supplied production database configuration.

### Native PostgreSQL on Windows

Install PostgreSQL 16 and ensure `psql` and `pg_isready` are on `PATH`. Start the installed Windows service without assuming its exact version suffix:

```powershell
$postgresService = Get-Service -Name "postgresql*" | Sort-Object Name | Select-Object -First 1
$postgresService | Format-Table -AutoSize
if ($postgresService.Status -ne "Running") {
    Start-Service -Name $postgresService.Name
}
```

For a first-time local role and database, open the administrative `psql` prompt:

```powershell
psql -h 127.0.0.1 -p 5432 -U postgres -d postgres
```

Run these commands inside `psql`. `\password` prompts for a password without placing it in shell history:

```text
CREATE ROLE signalwatch LOGIN;
\password signalwatch
CREATE DATABASE signalwatch OWNER signalwatch;
```

Configure `.env`:

```dotenv
DB_NAME=signalwatch
DB_USER=signalwatch
DB_HOST=127.0.0.1
DB_PORT=5432
```

Add a `DB_PASSWORD` line holding the password you entered at the `\password` prompt. It is read from `.env`, so it never appears in a shell command. Verify connectivity:

```powershell
pg_isready -h 127.0.0.1 -p 5432 -U signalwatch -d signalwatch
python manage.py migrate
```

### Redis through Docker Desktop

For native Django/Celery processes, run a loopback-only Redis container with append-only persistence:

```powershell
docker run --name signalwatch-redis `
  --restart unless-stopped `
  -p 127.0.0.1:6379:6379 `
  -v signalwatch-redis-data:/data `
  redis:7-alpine `
  redis-server --appendonly yes
```

Verify it:

```powershell
docker exec signalwatch-redis redis-cli ping
```

The expected protocol response is `PONG`. Keep these local URLs in `.env`:

```dotenv
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
```

This local Redis container has no application password and is bound only to loopback. Do not expose that unauthenticated configuration on a shared host.

## Run Django, Celery, and ASGI

Run each long-lived process in its own activated PowerShell terminal.

### ASGI web server

```powershell
python -m uvicorn config.asgi:application --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000/accounts/login/`. The health endpoint is `http://127.0.0.1:8000/health/`.

`python manage.py runserver` is suitable only for ordinary HTTP investigation after the application imports successfully. It is not the supported WebSocket test server here: the project has a WSGI application, uses Uvicorn for ASGI, and does not include the Daphne server that Channels traditionally uses with `runserver`. Test HTTP and WebSockets with the Uvicorn command above.

### Celery worker on Windows

Celery cannot use its normal Linux prefork pool on Windows. Use `solo` only for this local Windows limitation:

```powershell
celery -A config worker --pool=solo --loglevel=INFO
```

On Linux, including Docker and Render, omit `--pool=solo` and use the normal prefork pool:

```bash
celery -A config worker --loglevel=INFO
```

### Celery Beat on Windows

Run only one Beat process:

```powershell
celery -A config beat --loglevel=INFO --schedule="$env:TEMP\celerybeat-schedule"
```

On Linux:

```bash
celery -A config beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule
```

Never run two Beat schedulers against the same queue. Multiple Beat instances can enqueue duplicate periodic jobs.

### Migrations, superuser, and demo data

```powershell
python manage.py migrate
python manage.py createsuperuser
```

There is a custom `seed_demo_data` management command in this checkout. It creates or reuses a demo user, two demo projects, alert rules, generated alert triggers, notifications, and a backdated event history:

```powershell
python manage.py seed_demo_data
```

Options:

| Option | Default | Effect |
| --- | --- | --- |
| `--events N` | `420` | Number of events to generate across the demo projects |
| `--days N` | `14` | How far back the generated `created_at` timestamps are spread |
| `--owner USERNAME` | `demo` | Seed an existing account instead of the demo user. Matches a username or an email address. |
| `--reset` | off | Delete the target account's existing projects, events, alert rules, triggers, and notifications before seeding |

The command creates the demo superuser `demo` with the password `DemoPass123!` when no `--owner` is given, and prints the resulting project IDs, dashboard URLs, and API-key prefixes on completion. Change the demo password before exposing the application to anyone.

With `--owner`, the account's **existing** projects are used, so a real project immediately gains history. If that account has no projects, the two demo blueprints are created for it. `--reset` is scoped to the target account only; it never touches another user's data. Using an unknown `--owner` value fails with a `CommandError` instead of silently creating an account.

A verified run of `python manage.py seed_demo_data --events 420 --days 14 --reset` in this checkout produced 2 projects, 420 events, 2 alert triggers, and the associated notifications. A run of `python manage.py seed_demo_data --owner your-username --events 600 --days 21` populated an existing single-project account with 600 events, which then rendered 600 total / 168 errors / 432 successes and a 559 ms average response time on both the main dashboard and the project dashboard.

The command writes through the ORM, so it does not exercise the API or WebSocket layers. Use the API ingestion and WebSocket sections below to verify those paths.

## API ingestion

### API-key behavior

The monitoring UI creates a key in the form `rt_live_<selector>.<secret>`, stores only its SHA-256 hash and a non-secret prefix, and places the plaintext key in the session for the immediate creation response. Visiting the project detail consumes and removes that value. Regeneration replaces the hash immediately, invalidating the old key, and renders the new plaintext once. An existing plaintext key cannot be recovered from the database.

`POST /api/projects/` returns a new plaintext key once, in the `api_key` field of the creation response. The serializer drops that field from every other representation, so a later `GET` of the same project never returns it. There is no separate API-key model; the hash and prefix live on `monitoring.Project`.

The event endpoint accepts either header form:

```text
X-API-Key: rt_live_<selector>.<secret>
Authorization: ApiKey rt_live_<selector>.<secret>
```

A valid request is scoped to the project that owns the key. Sending a different `project_id` returns a permission error.

### Required event shape

`event_type`, `message`, `service`, `environment`, and `status_code` are all required. `message` must be non-blank and at most 2000 characters; `service` must be non-blank and at most 255 characters; `status_code` must be between 100 and 599. `response_time` is optional, accepts `null`, and is measured in milliseconds from 0 to 3600000. `metadata` is optional, must be a JSON object, and is limited to 65536 bytes once encoded. `custom_event_name` is required for `CUSTOM` events and rejected for every other type. `environment` accepts only `production`, `staging`, `development`, `test`, `qa`, or `local`. `project`, `ip_address`, `id`, and `created_at` are read-only: the project comes from the API key and the address from the request. Supported event types are:

- `API_REQUEST`
- `USER_LOGIN`
- `USER_LOGOUT`
- `DATABASE_ERROR`
- `APPLICATION_ERROR`
- `PAYMENT`
- `ORDER`
- `CUSTOM`

### Windows curl.exe example

`curl.exe` avoids PowerShell's `curl` alias. The API key is read without echo and converted only in memory:

```powershell
$secureApiKey = Read-Host "Project API key" -AsSecureString
$apiKey = [System.Net.NetworkCredential]::new("", $secureApiKey).Password
$json = @'
{
  "event_type": "API_REQUEST",
  "message": "GET /health completed",
  "service": "demo-api",
  "environment": "local",
  "response_time": 87,
  "status_code": 200,
  "metadata": {
    "request_path": "/health/",
    "attempt": 1
  }
}
'@
curl.exe --fail --silent --show-error `
  --request POST `
  --url "http://127.0.0.1:8000/api/events/" `
  --header "X-API-Key: $apiKey" `
  --header "Content-Type: application/json" `
  --data-binary $json
Remove-Variable apiKey, secureApiKey
```

A successful request returns HTTP `201` with the created event, including the server-assigned `id`, `project`, `ip_address`, and `created_at`.

### PowerShell Invoke-RestMethod example

```powershell
$secureApiKey = Read-Host "Project API key" -AsSecureString
$apiKey = [System.Net.NetworkCredential]::new("", $secureApiKey).Password
$headers = @{
    "X-API-Key" = $apiKey
    "Content-Type" = "application/json"
}
$body = @{
    event_type = "APPLICATION_ERROR"
    message = "Checkout failed"
    service = "checkout-api"
    environment = "local"
    response_time = 425
    status_code = 500
    metadata = @{
        order_id = 1001
        retryable = $true
    }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/events/" `
    -Method Post `
    -Headers $headers `
    -Body $body
Remove-Variable apiKey, secureApiKey, headers, body
```

### Postman-compatible event request

1. Create a POST request to `http://127.0.0.1:8000/api/events/`.
2. Add an `X-API-Key` header with the one-time project key.
3. Select **Body → raw → JSON**.
4. Send the same JSON object shown in the curl example.
5. Expect JSON in the response. A `201` is the intended success status; `400` is validation, `401` is missing/invalid key, and `403` is an inactive or mismatched project.

### Event filtering, ordering, and pagination

`GET /api/events/` uses the authenticated Django session. Query parameters are:

| Parameter | Behavior |
| --- | --- |
| `project` | Integer project ID |
| `date_from` | ISO-8601 date or datetime, inclusive |
| `date_to` | ISO-8601 date or datetime, inclusive; a date-only value covers that entire UTC day |
| `event_type` | Exact event type |
| `service` | Exact service |
| `environment` | Exact environment |
| `status_code` | Integer from 100 through 599 |
| `slow` | `true` selects response time greater than or equal to `SLOW_REQUEST_THRESHOLD`; `false` does not add a slow filter |
| `search` | Case-insensitive partial match in the event fields that exist on the model: `message`, `event_type`, `service`, `environment`, and `ip_address` |
| `ordering` | Comma-separated fields; prefix a field with `-` for descending order |
| `page` | Page number; default is 1 |
| `page_size` | Page size; default is 50, maximum is 200 |

Allowed ordering fields are `created_at`, `event_type`, `service`, `environment`, `response_time`, and `status_code`. The default is newest first. Paginated responses use this shape:

```json
{
  "count": 0,
  "next": null,
  "previous": null,
  "results": []
}
```

The example shows the envelope only; it is not a performance or volume claim.

`GET /api/analytics/` supports `project`, `date_from`, `date_to`, `event_type`, `service`, repeated or comma-separated `services`, `environment`, `status_code`, `slow`, and `search`. It is not paginated. The response contains an `overview` object with totals for today, this week, this month, error and success counts, the error rate, and average, minimum, maximum, p50, p95, and p99 response times; an hourly `timeline`; grouped `event_types`, `services`, `environments`, and `status_codes`; the resolved `project` or `null`; and an echo of the applied `filters`. With no `date_from`, the window starts seven days before the request. Results are cached for `ANALYTICS_CACHE_TTL` seconds and the cache is versioned, so a new event or a cache-version bump makes the next request recompute instead of serving a stale window.

`GET /api/notifications/` additionally accepts `is_read` (`true` or `false`) and orders by `created_at` or `is_read`.

### UI event filters and CSV export

The project event page supports exact event type, partial custom event name, case-insensitive exact service, case-insensitive exact environment, one or more status codes separated by commas or spaces, and `date_from`/`date_to` date fields that each cover a whole UTC day. It displays 50 events per page.

CSV export uses the same filters and streams every matching event rather than only the current page:

```text
/projects/{project_id}/events/export/?event_type=APPLICATION_ERROR&environment=production
```

The response filename is `events-{project_id}.csv`. It includes a UTF-8 BOM for spreadsheet compatibility and columns for ID, event type, custom name, message, service, environment, status, response time, IP address, metadata JSON, and creation time.

## WebSockets and browser testing

The ASGI router serves three WebSocket routes:

```text
/ws/projects/{project_id}/stream/
/ws/users/{user_id}/notifications/
/ws/notifications/
```

The first two come from `monitoring/routing.py`; `/ws/notifications/` comes from `notifications/routing.py` and is the path the base template uses for the notification dropdown. On `/ws/projects/{project_id}/stream/` the signed-in user must own the project. On `/ws/users/{user_id}/notifications/` the URL's user ID must match the signed-in user.

Project-stream authorization closes unauthenticated sockets with code `4401` and a non-owner with code `4403`. `AllowedHostsOriginValidator` can reject a connection before the consumer runs when the browser origin is not allowed.

### Browser and DevTools test

1. Start PostgreSQL and Redis.
2. Start migrations, Uvicorn, Celery worker, and one Celery Beat process.
3. Log in at `/accounts/login/` in the same browser that will open the WebSocket.
4. Open a project dashboard or the main dashboard filtered to that project.
5. In browser developer tools, open **Network**, select **WS**, and reload the page.
6. For a direct project-socket check, run this in the browser console using an actual owned project ID:

```javascript
const projectId = 1;
const scheme = window.location.protocol === "https:" ? "wss" : "ws";
const socket = new WebSocket(
  `${scheme}://${window.location.host}/ws/projects/${projectId}/stream/`
);
socket.addEventListener("open", () => console.log("SignalWatch socket open"));
socket.addEventListener("message", event => console.log("SignalWatch event", event.data));
socket.addEventListener("close", event => console.log("SignalWatch socket closed", event.code));
```

A successful upgrade is HTTP `101`. That confirms only the handshake. Frame delivery additionally requires the Redis channel layer: with `REDIS_URL` unset, the in-memory channel layer only reaches sockets inside the same process, so a Celery worker or a separate Uvicorn process cannot push to a browser. `static/js/realtime.js` is present and opens both sockets automatically, so a page that exposes `data-realtime-project-id` should show a `101` for the project stream and a `101` for `/ws/notifications/` without any manual console work.

### Reconnect behavior

`static/js/realtime.js` manages both sockets. On every close it reconnects with exponential backoff: the delay starts at 1000 ms, doubles per attempt, is capped at 30000 ms, and adds up to 30 percent jitter. The header indicator elements `data-connection-dot` and `data-connection-status` show `Connecting`, `Live`, `Offline`, or `Reconnecting`. The project socket opens only when the page exposes `data-realtime-project-id`, which the project dashboard, the project detail page, and the main dashboard with a project filter all do. Connections stop on `beforeunload` and are suspended while the tab is hidden, then restarted when the tab becomes visible again. There is no session renewal and no message replay: events that occur while a socket is down are not recovered by the socket, and a page reload reads them from the database instead.

## Docker image and Compose

### Image behavior

`Dockerfile` uses `python:3.12-slim`, installs only `requirements.txt`, copies an allow-listed source context, runs `collectstatic --noinput`, switches to the non-root `app` user, exposes port 8000, and starts Uvicorn on `0.0.0.0:8000`. WhiteNoise is already first in Django middleware and uses manifest static storage.

`.dockerignore` starts from a deny-all rule and re-includes only the Django project directories, `manage.py`, `requirements.txt`, and the `media/.gitkeep` marker. Local uploads, `.env`, Git metadata, virtual environments, caches, SQLite data, collected static output, and every other unlisted file stay out of the build context, so no local secret or database file reaches the image. Compose mounts a persistent media volume at `/app/media`.

`collectstatic` gathers `static/css/app.css`, `static/js/app.js`, `static/js/dashboard.js`, and `static/js/realtime.js` into `/app/staticfiles`. All four exist, so that build step is expected to succeed. The image installs `django-redis` from `requirements.txt`, so the `REDIS_URL`-driven cache backend resolves in every Compose process.

### Compose configuration

Compose provides:

- Health-checked PostgreSQL 16 with a named persistent volume.
- Health-checked Redis 7 with append-only persistence and no host port.
- A one-shot `migrate` service that must complete before application processes start.
- A health-checked `web` service bound to `127.0.0.1:8000`.
- A Celery worker using Linux prefork by default.
- One Celery Beat service.
- Internal service URLs: `postgres:5432` and `redis:6379`.
- A persistent `media_data` volume shared with the web service.
- No hardcoded Django secret or PostgreSQL password; both come from `.env`.

Before starting, copy `.env`, generate `SECRET_KEY`, and set non-empty `DB_NAME`, `DB_USER`, and `DB_PASSWORD`. Compose intentionally does not publish PostgreSQL or Redis to the host. Because Compose sets `REDIS_URL`, every process uses the `django_redis` cache backend and the Redis channel layer; both are provided by pinned dependencies.

These Compose commands could not be executed in this checkout because no Docker daemon is available in the environment used to verify the code. The file is written from the source; run the commands below yourself to confirm the stack on a machine with Docker Desktop.

Validate and run:

```powershell
Copy-Item .env.example .env
docker compose config
docker compose build
docker compose up -d
docker compose ps -a
```

The `migrate` container should show exited with status 0. `web`, `worker`, and `beat` should be running. Follow logs:

```powershell
docker compose logs -f web worker beat
```

Run migrations explicitly after code or migration changes:

```powershell
docker compose run --rm migrate
```

Create an administrator inside the running web container:

```powershell
docker compose exec web python manage.py createsuperuser
```

Run a Django check in the image:

```powershell
docker compose exec web python manage.py check
```

Inspect data services:

```powershell
docker compose exec postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose exec redis redis-cli ping
```

The `sh -c` form expands `POSTGRES_USER` and `POSTGRES_DB` inside the container, so it stays correct if you change `DB_USER` or `DB_NAME` in `.env`.

Stop containers without deleting persistent data:

```powershell
docker compose down
```

Delete containers and all named database, Redis, and media data only when intentional:

```powershell
docker compose down --volumes
```

Rebuild after dependency or source changes:

```powershell
docker compose up -d --build
```

## Available checks and tests

There is no `pyproject.toml`, package manifest, Ruff configuration, mypy configuration, or Pyright configuration in this checkout, so no lint or type-check command is offered. There is a custom test suite in `tests/`, run with a dedicated settings module.

`config/settings_test.py` isolates the suite from any local or deployed configuration: an in-memory SQLite database, the local-memory cache, the in-memory channel layer, Celery in eager mode, the fast MD5 password hasher, and the local-memory email backend. Running the suite therefore never touches `db.sqlite3`, `config/settings.py` secrets, or a real Redis instance.

| Purpose | Command | Verified result |
| --- | --- | --- |
| Python syntax compilation | `python -m compileall -q accounts analytics api config dashboard monitoring notifications` | Passes |
| Django system check | `python manage.py check` | `System check identified no issues (0 silenced).` |
| Migration drift | `python manage.py makemigrations --check --dry-run` | `No changes detected` |
| Deployment check | `python manage.py check --deploy` with `DEBUG=False` and a real `SECRET_KEY` | No issues other than the placeholder-secret warning caused by the test secret string |
| OpenAPI schema generation | `python manage.py spectacular --file schema.yml` | Generates with zero warnings, including the `ApiKeyAuth` security scheme |
| Test suite | `python manage.py test tests --settings=config.settings_test` | `Ran 114 tests ... OK` |
| Lint | None available | No configured or installed project linter |
| Type check | None available | No configured or installed type checker |

The suite covers:

| File | Focus |
| --- | --- |
| `tests/factories.py` | Shared model factories for users, projects, events, alert rules, and notifications |
| `tests/test_accounts_and_models.py` | Registration, login, profile and avatar handling, password flows, model constraints and helper methods |
| `tests/test_monitoring.py` | Ownership boundaries, project and event views, alert rules, activity log, CSV export, and Celery task behavior |
| `tests/test_analytics.py` | Aggregations, percentile math, filter forms, `error_q` / `success_q` semantics, cache versioning, and daily summaries |
| `tests/test_api.py` | API-key authentication, event ingestion, DRF list and create permissions, filtering, and pagination |
| `tests/test_dashboard_and_realtime.py` | Dashboard context and templates, `seed_demo_data`, and both WebSocket consumers including group naming and payload shape |

Run the checks locally before building:

```powershell
python -m compileall -q accounts analytics api config dashboard monitoring notifications
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test tests --settings=config.settings_test
python manage.py spectacular --file schema.yml
```

For a deployment check, provide a real secret and production-like host values without committing them:

```powershell
$env:DEBUG = "False"
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(64))"
$env:ALLOWED_HOSTS = "localhost,127.0.0.1"
python manage.py check --deploy
Remove-Item Env:DEBUG, Env:SECRET_KEY, Env:ALLOWED_HOSTS
```

## Git and GitHub CLI

These commands are provided for execution by the repository owner and have not been run as part of creating this documentation.

Initialize and commit the current tree:

```powershell
Set-Location "C:\Users\hp\Desktop\Real time analytics platform"
git init
git add .
git status
git commit -m "Build SignalWatch monitoring platform"
git branch -M main
```

Authenticate GitHub CLI and create a private repository with the current folder as its source:

```powershell
gh auth login
gh repo create signalwatch --private --source=. --remote=origin --push
```

For a repository that already exists on GitHub, obtain its URL from GitHub CLI rather than hardcoding one:

```powershell
$repositoryUrl = gh repo view --json url --jq .url
git remote add origin $repositoryUrl
git push -u origin main
```

Inspect the remote after pushing:

```powershell
git status
git log --oneline -10
gh repo view --web
```

## Render deployment

`render.yaml` is a Render Blueprint for native Python services; it does not use the supplied Dockerfile. It declares:

- `signalwatch-web`: Uvicorn bound to `0.0.0.0` and Render's dynamic `$PORT`.
- `signalwatch-worker`: Celery's normal Linux prefork pool.
- `signalwatch-beat`: exactly one Beat instance.
- `signalwatch-redis`: a private Render Key Value/Valkey instance.
- `signalwatch-db`: a private managed PostgreSQL database.
- `python manage.py migrate --noinput` as the web service's pre-deploy command.
- A generated Django `SECRET_KEY`, managed database values, and Redis connection strings.

### Create the Blueprint

1. Push the repository to GitHub.
2. In Render, create a new Blueprint and select the repository.
3. Render reads `render.yaml` from the repository root.
4. Set `ALLOWED_HOSTS` to the exact web hostname only, without scheme, for example `signalwatch-web.onrender.com` if that is the generated hostname.
5. Set `CSRF_TRUSTED_ORIGINS` to the exact HTTPS origin, including scheme, for example `https://signalwatch-web.onrender.com` if that is the generated hostname.
6. The Blueprint starts with Django's console email backend, which works without external configuration but writes message bodies to service logs instead of sending mail. To send real email, change `EMAIL_BACKEND` to your SMTP backend and set `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `DEFAULT_FROM_EMAIL` in Render. The worker and Beat services inherit those same values.
7. Deploy and review the web build, pre-deploy migration, and worker logs.
8. Create the first administrator from the Render web service shell:

```bash
python manage.py createsuperuser
```

Do not run migrations independently from every service. The Blueprint's single pre-deploy migration is the intended deployment step; rerun it only when Render has not applied the migration or when an operational migration procedure explicitly requires it.

### ASGI, WebSockets, origins, and Redis Channels

The start command is equivalent to:

```bash
uvicorn config.asgi:application --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips='*'
```

Render terminates public TLS. Browsers connect to:

```text
wss://the-exact-web-hostname/ws/projects/{project_id}/stream/
wss://the-exact-web-hostname/ws/users/{user_id}/notifications/
wss://the-exact-web-hostname/ws/notifications/
```

Add the exact public hostname to `ALLOWED_HOSTS` and its HTTPS origin to `CSRF_TRUSTED_ORIGINS`. Do not use a broad wildcard for production. `REDIS_URL` comes from the Key Value service and configures the Redis channel layer and Django cache through the pinned `django-redis` distribution.

### Celery worker and Beat caveat

Keep `signalwatch-worker` on prefork on Linux. Do not add `--pool=solo` to Render. Multiple worker instances are safe only after verifying task idempotency and database capacity; the supplied configuration starts one.

Keep `numInstances: 1` for `signalwatch-beat`. Never scale Beat to two or more instances and do not run a second Beat service or local Beat process against the Render queue. Two schedulers can enqueue each periodic task more than once.

Render's filesystem is ephemeral. The `media/` directory is not a durable Render disk in this Blueprint. Profile pictures uploaded after a deploy can be lost when an instance is replaced. Add and configure a durable storage backend before relying on uploaded media in production.

## Environment variables

| Variable | Required | Default or example | Effect |
| --- | --- | --- | --- |
| `SECRET_KEY` | Production: yes | No safe default | Django cryptographic signing. With `DEBUG=False`, startup fails if empty. |
| `DEBUG` | No | `True` in code; Docker/Compose and Render set `False` | Enables debug behavior and disables several production security settings. |
| `ALLOWED_HOSTS` | Production: yes | `localhost,127.0.0.1` | Comma-separated HTTP host allowlist used by Django and Channels origin validation. |
| `CSRF_TRUSTED_ORIGINS` | Required for a nonmatching HTTPS origin | Empty | Comma-separated origins including scheme, for example `https://app.example.com`. |
| `SECURE_SSL_REDIRECT` | No | `True` when `DEBUG=False` | Redirects HTTP to HTTPS. Compose defaults it to `False` for local HTTP. |
| `DB_NAME` | PostgreSQL: yes | Empty | PostgreSQL database name. `DB_NAME`, `DB_USER`, and `DB_HOST` must all be non-empty to select PostgreSQL. |
| `DB_USER` | PostgreSQL: yes | Empty | PostgreSQL login role. |
| `DB_PASSWORD` | Production PostgreSQL: yes | Empty | PostgreSQL password. Compose requires a non-empty value. |
| `DB_HOST` | PostgreSQL: yes | Empty | Use `localhost` natively, `postgres` in Compose, or the managed Render host. |
| `DB_PORT` | No | `5432` | PostgreSQL port. |
| `REDIS_URL` | Redis features: yes | Empty in settings; URLs in `.env.example` | Enables the `django_redis` cache and the Redis channel layer. Empty uses the local-memory cache and channel layer, which limits WebSocket delivery and Celery to one process. Requires the pinned `django-redis` distribution. |
| `CELERY_BROKER_URL` | Celery with Redis: yes | Falls back to `REDIS_URL`, then memory | Celery broker URL. |
| `CELERY_RESULT_BACKEND` | Celery with Redis: yes | Falls back to `REDIS_URL`, then memory | Celery result backend URL. |
| `EMAIL_BACKEND` | No | `django.core.mail.backends.console.EmailBackend` | Use a valid Django email backend. An explicitly empty value is not equivalent to omitting the variable. |
| `EMAIL_HOST` | SMTP: yes | Empty | SMTP server hostname. |
| `EMAIL_PORT` | SMTP: yes | `587` | SMTP port. |
| `EMAIL_HOST_USER` | Depends on SMTP provider | Empty | SMTP username. |
| `EMAIL_HOST_PASSWORD` | Depends on SMTP provider | Empty | SMTP password or provider credential. |
| `EMAIL_USE_TLS` | No | `True` | Enables STARTTLS for the SMTP backend. |
| `DEFAULT_FROM_EMAIL` | Email sending: yes | `monitoring@localhost` in code | Sender address for report and notification email. |
| `SLOW_REQUEST_THRESHOLD` | No | `1000` | Response time in milliseconds. UI project cards use greater-than; API and analytics slow filters use greater-than-or-equal. |
| `EVENT_RETENTION_DAYS` | No | `90` | Age used by the event-cleanup Celery task. |
| `ANALYTICS_CACHE_TTL` | No | `30` | Dashboard analytics cache duration in seconds. A non-positive value bypasses dashboard caching. |
| `ERROR_SPIKE_THRESHOLD` | No | `5` | Minimum error count in the current five-minute window before `monitoring.tasks.detect_abnormal_error_spikes` can create a trigger. |
| `ERROR_SPIKE_MULTIPLIER` | No | `3` | Ratio the current five-minute error count must reach, relative to the previous window, for a spike trigger. |
| `LOG_LEVEL` | No | `INFO` | Root Python logging level. |
| `PORT` | Render: supplied | Dynamic | Uvicorn must bind to Render's supplied port. The Docker image listens on 8000. |
| `DJANGO_SETTINGS_MODULE` | No | `config.settings` by entry points | Selects settings for management, Celery, and ASGI processes. |

## Security notes

- Never commit `.env`, database passwords, SMTP credentials, API keys, or Render secrets. `.gitignore` and `.dockerignore` exclude `.env` from Git and the image context.
- Use a unique high-entropy `SECRET_KEY` per environment. Render generates one in the Blueprint; local and Compose deployments must supply one.
- Keep `DEBUG=False` in any shared environment. In production mode, current settings enable secure session and CSRF cookies, HSTS, proxy SSL recognition, content-type protection, and denied framing.
- Set exact `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`; do not solve origin errors with `*`.
- Keep PostgreSQL and Redis private. Compose does not publish their ports. Render's Key Value and database use private allowlists.
- Compose Redis is intentionally unauthenticated only inside its local Docker setup. Do not publish port 6379 or reuse that command on a shared host.
- API keys are bearer secrets. They are shown once, stored hashed, and invalidated on rotation. Never log the `X-API-Key` or `Authorization` header.
- Project, event, alert, and notification access is owner-scoped or user-scoped in the implemented views and API querysets, and those boundaries are covered by the test suite. Continue testing them after any change.
- DRF throttling is not configured for event ingestion. Apply gateway or platform rate limits and request-size monitoring before exposing ingestion publicly.
- Static assets are served by WhiteNoise. Uploaded media uses local filesystem storage; Docker preserves it only through `media_data`, and the supplied Render Blueprint does not provide durable media.
- Email defaults to the console backend. Configure a real provider, sender address, and credentials for a deployed environment.

## Troubleshooting

### PowerShell says `Activate.ps1` cannot be loaded

Use the process-only fallback shown earlier:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Do not replace it with a machine-wide policy change.

### `ModuleNotFoundError: No module named 'django_redis'`

`config/settings.py` selects `django_redis.cache.RedisCache` whenever `REDIS_URL` is set, and `requirements.txt` pins `django-redis==6.0.0`. This error means the environment is missing that install. Run `pip install -r requirements.txt` inside the activated virtual environment, or rebuild the image so the pinned dependency is installed. Leaving `REDIS_URL` empty also avoids the import, but that falls back to the in-memory cache and in-memory channel layer, which does not support Celery or WebSockets across processes, so it is not a deployment answer.

### A page raises `TemplateSyntaxError: Invalid filter: 'intcomma'`

Templates apply `|intcomma`, which this project provides through its own template library at `dashboard/templatetags/dashboard_tags.py` rather than through `django.contrib.humanize`. The error means the affected template is missing `{% load dashboard_tags %}`. Add that load tag to the template. Do not paper over it by removing the filter; the affected numbers are counts, durations, and paginated totals.

### WebSocket closes with `4401`

The browser is not authenticated. Log in through the same host and keep the session cookie in the WebSocket request.

### WebSocket closes with `4403`

The signed-in user does not own the project in the URL.

### WebSocket is rejected as a bad origin

Add the exact public HTTPS origin to `CSRF_TRUSTED_ORIGINS` and the exact hostname to `ALLOWED_HOSTS`, then restart every web process. Local Uvicorn should use the same hostname, normally `127.0.0.1` or `localhost`, that is in `ALLOWED_HOSTS`.

### WebSocket opens but receives no frames

A `101` only confirms the upgrade. Confirm the group name matches on both sides: event ingestion publishes to `monitoring_project_{project_id}`, which `ProjectStreamConsumer` joins, and notifications publish to `user_{user_id}`, which `UserNotificationConsumer` joins. If the socket is open but silent, check that `REDIS_URL` is set so the Redis channel layer is in use, that the Celery worker and the web process are both running, and that the event was actually created. A `4403` close means ownership failed, and a rejected origin means `ALLOWED_HOSTS` or `CSRF_TRUSTED_ORIGINS` needs the exact host.

### Browser redirects HTTP to HTTPS locally

Production settings default `SECURE_SSL_REDIRECT` to `True` when `DEBUG=False`. Keep `DEBUG=True` for local HTTP, or set `SECURE_SSL_REDIRECT=False` in the local Compose environment. Do not disable it on the public Render service.

### PostgreSQL is unhealthy or rejects authentication

Inspect `.env` without posting the password publicly:

```powershell
docker compose config
docker compose logs postgres
docker compose exec postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

For native PostgreSQL, verify the Windows service and `pg_isready` host, port, role, and database. If a volume was initialized with old credentials, changing `.env` does not update the existing PostgreSQL role; either update the role securely or deliberately recreate the data volume.

### Redis is unhealthy

```powershell
docker compose ps redis
docker compose logs redis
docker compose exec redis redis-cli ping
```

For the native-process setup, use `docker exec signalwatch-redis redis-cli ping`. Check that `.env` uses `127.0.0.1`, not the Compose-only hostname `redis`.

### Celery cannot connect

Verify broker and result URLs, Redis health, and migration completion. On Windows, only the worker command needs `--pool=solo`; Beat does not use a worker pool. In Linux containers, remove `--pool=solo`.

### Duplicate periodic jobs

Stop every extra Beat process. Keep the Render Beat service at one instance and do not run a host Beat process against the same broker. Restart the single Beat process after changing its schedule.

### Port 8000 is already in use

```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
python -m uvicorn config.asgi:application --host 127.0.0.1 --port 8001 --reload
```

Use the matching URL in the browser.

### No lint or type-check command exists

Do not add claims about Ruff, Flake8, mypy, Pyright, or pytest to CI until their dependencies and configuration are actually added. The currently available project checks are listed above.
