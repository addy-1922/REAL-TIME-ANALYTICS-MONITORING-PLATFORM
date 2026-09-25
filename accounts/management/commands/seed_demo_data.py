import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Profile
from monitoring.models import AlertRule, AlertTrigger, Event, Project
from notifications.models import Notification

User = get_user_model()

DEMO_PASSWORD = "DemoPass123!"
DEMO_USERNAME = "demo"
DEMO_EMAIL = "demo@example.com"

SERVICES = ("api-gateway", "auth-service", "billing-worker", "web-frontend")
ENVIRONMENTS = ("production", "staging")
STATUS_SUCCESS = (200, 201, 202, 204, 301, 302)
STATUS_CLIENT_ERROR = (400, 401, 403, 404, 409, 422)
STATUS_SERVER_ERROR = (500, 502, 503, 504)

PROJECT_BLUEPRINTS = (
    ("Storefront API", "Public storefront traffic and checkout flow."),
    ("Internal Platform", "Shared services, workers and internal tooling."),
)


class Command(BaseCommand):
    help = "Populate the database with realistic demo users, projects, events and alerts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--events",
            type=int,
            default=420,
            help="Total number of events to generate across the demo projects.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=14,
            help="Number of days of event history to spread the generated data over.",
        )
        parser.add_argument(
            "--owner",
            default="",
            help=(
                "Seed an existing account instead of the demo user. The "
                "account's current projects are used; if it has none, the demo "
                "project blueprints are created for it."
            ),
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing data for the target account before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(20240617)
        event_count = max(0, int(options["events"]))
        days = max(1, int(options["days"]))
        owner_username = (options["owner"] or "").strip()

        if owner_username:
            user = self._resolve_existing_user(owner_username)
        else:
            user = self._ensure_demo_user()

        if options["reset"]:
            self._reset(user)

        projects = self._ensure_projects(user)
        self._ensure_alert_rules(projects)

        created_events = self._create_events(projects, event_count, days)
        triggers = self._create_sample_triggers(projects)
        self._create_sample_notifications(user, projects, triggers)

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
        if not owner_username:
            self.stdout.write(
                f"  Demo user: {DEMO_USERNAME} / {DEMO_PASSWORD}"
            )
        self.stdout.write(f"  Owner: {user.username}")
        for project in projects:
            self.stdout.write(
                f"  Project: {project.name} (id={project.pk}, "
                f"api_key_prefix={project.api_key_prefix})"
            )
        self.stdout.write(f"  Events created: {created_events}")
        self.stdout.write(f"  Alert triggers created: {len(triggers)}")

    def _resolve_existing_user(self, username):
        user = User.objects.filter(username=username).first()
        if user is None:
            user = User.objects.filter(email=username).first()
        if user is None:
            raise CommandError(
                f"No user matches username or email {username!r}. "
                "Register the account first, or omit --owner to seed the demo user."
            )
        if not user.is_active:
            self.stdout.write(
                self.style.WARNING(f"User {user.username!r} is inactive; seeding anyway.")
            )
        self.stdout.write(f"Using existing user '{user.username}'.")
        return user

    def _reset(self, user):
        """Delete data owned by this account only, leaving other users untouched."""
        projects = Project.objects.filter(owner=user)
        Event.objects.filter(project__in=projects).delete()
        AlertTrigger.objects.filter(project__in=projects).delete()
        AlertRule.objects.filter(project__in=projects).delete()
        Notification.objects.filter(user=user).delete()
        projects.delete()
        self.stdout.write(f"Existing data for {user.username!r} removed.")

    def _ensure_demo_user(self):
        user, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={"email": DEMO_EMAIL, "is_staff": True, "is_superuser": True},
        )
        user.email = DEMO_EMAIL
        user.is_staff = True
        user.is_superuser = True
        user.set_password(DEMO_PASSWORD)
        user.save()
        Profile.objects.update_or_create(
            user=user,
            defaults={
                "job_title": "Platform Engineer",
                "bio": "Demo account used to explore SignalWatch dashboards.",
                "timezone": "UTC",
                "daily_report_enabled": True,
            },
        )
        if created:
            self.stdout.write(f"Created demo superuser '{DEMO_USERNAME}'.")
        else:
            self.stdout.write(f"Reused demo superuser '{DEMO_USERNAME}'.")
        return user

    def _ensure_projects(self, user):
        existing = list(
            Project.objects.filter(owner=user).order_by("id")
        )
        if existing:
            self.stdout.write(
                f"Using {len(existing)} existing project(s) for {user.username}."
            )
            for project in existing:
                if not project.api_key_hash:
                    self._assign_api_key(project)
            return existing

        projects = []
        for name, description in PROJECT_BLUEPRINTS:
            project = Project(
                owner=user,
                name=name,
                description=description,
                is_active=True,
            )
            self._assign_api_key(project)
            project.save()
            projects.append(project)
        return projects

    def _assign_api_key(self, project):
        api_key = Project.generate_api_key()
        project.api_key_hash = Project.hash_api_key(api_key)
        project.api_key_prefix = Project.key_prefix(api_key)
        if project.pk:
            project.save(
                update_fields=["api_key_hash", "api_key_prefix", "updated_at"]
            )

    def _ensure_alert_rules(self, projects):
        blueprints = (
            (
                "High error count",
                AlertRule.Metric.ERROR_COUNT,
                AlertRule.Condition.GTE,
                Decimal("25"),
                15,
                30,
            ),
            (
                "Elevated error rate",
                AlertRule.Metric.ERROR_RATE,
                AlertRule.Condition.GT,
                Decimal("12.5"),
                30,
                45,
            ),
            (
                "Slow responses",
                AlertRule.Metric.AVG_RESPONSE_TIME,
                AlertRule.Condition.GT,
                Decimal("1500"),
                10,
                20,
            ),
        )
        for project in projects:
            for name, metric, condition, threshold, window, cooldown in blueprints:
                AlertRule.objects.get_or_create(
                    project=project,
                    name=name,
                    defaults={
                        "metric": metric,
                        "condition": condition,
                        "threshold": threshold,
                        "time_window_minutes": window,
                        "cooldown_minutes": cooldown,
                        "is_active": True,
                    },
                )

    def _create_events(self, projects, count, days):
        if count == 0:
            return 0
        now = timezone.now()
        start = now - timedelta(days=days)
        span_seconds = max(1, int((now - start).total_seconds()))
        created = []
        for _ in range(count):
            project = random.choice(projects)
            created_at = start + timedelta(seconds=random.randint(0, span_seconds))
            event_type, status_code, response_time, message = self._random_event()
            created.append(
                Event(
                    project=project,
                    event_type=event_type,
                    custom_event_name=(
                        random.choice(["checkout_completed", "signup_completed"])
                        if event_type == Event.EventType.CUSTOM
                        else ""
                    ),
                    message=message,
                    service=random.choice(SERVICES),
                    environment=random.choice(ENVIRONMENTS),
                    response_time=response_time,
                    status_code=status_code,
                    metadata={
                        "method": random.choice(["GET", "POST", "PUT", "DELETE"]),
                        "path": random.choice(
                            ["/api/orders", "/api/users", "/health", "/api/checkout"]
                        ),
                        "request_id": f"req-{random.randint(100000, 999999)}",
                    },
                    ip_address=f"203.0.113.{random.randint(1, 254)}",
                    created_at=created_at,
                )
            )
        Event.objects.bulk_create(created, batch_size=500)
        return len(created)

    def _random_event(self):
        roll = random.random()
        if roll < 0.12:
            return (
                Event.EventType.APPLICATION_ERROR,
                random.choice((500, 502, 503)),
                random.randint(5, 400),
                "Unhandled exception while processing the request.",
            )
        if roll < 0.16:
            return (
                Event.EventType.DATABASE_ERROR,
                random.choice((500, 503)),
                random.randint(20, 900),
                "Database connection pool exhausted.",
            )
        if roll < 0.28:
            return (
                Event.EventType.API_REQUEST,
                random.choice(STATUS_CLIENT_ERROR),
                random.randint(10, 900),
                "Client request rejected.",
            )
        if roll < 0.4:
            return (
                Event.EventType.API_REQUEST,
                200,
                random.randint(800, 3200),
                "Slow endpoint response.",
            )
        if roll < 0.6:
            return (
                Event.EventType.USER_LOGIN,
                200,
                random.randint(40, 400),
                "User authenticated successfully.",
            )
        if roll < 0.75:
            return (
                Event.EventType.ORDER,
                201,
                random.randint(90, 900),
                "Order created.",
            )
        if roll < 0.9:
            return (
                Event.EventType.PAYMENT,
                200,
                random.randint(120, 1200),
                "Payment processed.",
            )
        return (
            Event.EventType.API_REQUEST,
            random.choice(STATUS_SUCCESS),
            random.randint(15, 700),
            "Request completed.",
        )

    def _create_sample_triggers(self, projects):
        now = timezone.now()
        triggers = []
        for project in projects:
            rule = (
                AlertRule.objects.filter(project=project, is_active=True)
                .order_by("id")
                .first()
            )
            if rule is None:
                continue
            triggers.append(
                AlertTrigger.objects.create(
                    rule=rule,
                    project=project,
                    title=f"{rule.name} triggered",
                    message=(
                        f"{rule.get_metric_display()} reached "
                        f"{rule.threshold} for project {project.name}."
                    ),
                    metric_value=rule.threshold,
                    triggered_at=now - timedelta(hours=random.randint(1, 20)),
                )
            )
        return triggers

    def _create_sample_notifications(self, user, projects, triggers):
        if Notification.objects.filter(user=user).exists():
            return
        now = timezone.now()
        drafts = []
        for index, project in enumerate(projects):
            drafts.append(
                Notification(
                    user=user,
                    project=project,
                    title=f"Welcome to {project.name}",
                    message=(
                        "This project is receiving demo traffic. "
                        "Open the dashboard to explore live analytics."
                    ),
                    notification_type=Notification.NotificationType.PROJECT,
                    is_read=index > 0,
                )
            )
        for trigger in triggers:
            drafts.append(
                Notification(
                    user=user,
                    project=trigger.project,
                    title=trigger.title,
                    message=trigger.message,
                    notification_type=Notification.NotificationType.ERROR_ALERT,
                    is_read=False,
                )
            )
        created = Notification.objects.bulk_create(drafts, batch_size=200)
        for notification in created:
            backdated = now - timedelta(hours=random.randint(1, 30))
            notification.created_at = backdated
            notification.save(update_fields=["created_at"])
