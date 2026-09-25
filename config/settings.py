import os
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    value = os.getenv(name, default).strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    items = (item.strip().strip("'\"") for item in value.split(","))
    return [item for item in items if item]


def database_config_from_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("DATABASE_URL must use a PostgreSQL URL scheme")

    name = unquote(parsed.path.lstrip("/"))
    if not name or not parsed.hostname:
        raise ImproperlyConfigured("DATABASE_URL must include a host and database name")

    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": parsed.port or 5432,
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
    options = dict(parse_qsl(parsed.query))
    if options:
        config["OPTIONS"] = options
    return config


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_RENDER = env_bool("RENDER", False)
if IS_RENDER and not DATABASE_URL:
    raise ImproperlyConfigured("DATABASE_URL must be set on Render")
DEBUG = env_bool("DEBUG", not (IS_RENDER or bool(DATABASE_URL)))

SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = secrets.token_urlsafe(50)
    else:
        raise RuntimeError("SECRET_KEY is required when DEBUG is False")

ALLOWED_HOSTS = list(
    dict.fromkeys(
        [
            "localhost",
            "127.0.0.1",
            "real-time-analytics-monitoring-platform-2.onrender.com",
            *env_list("ALLOWED_HOSTS"),
        ]
    )
)
CSRF_TRUSTED_ORIGINS = list(
    dict.fromkeys(
        [
            "https://real-time-analytics-monitoring-platform-2.onrender.com",
            *env_list("CSRF_TRUSTED_ORIGINS"),
        ]
    )
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "channels",
    "accounts.apps.AccountsConfig",
    "monitoring.apps.MonitoringConfig",
    "analytics.apps.AnalyticsConfig",
    "api.apps.ApiConfig",
    "notifications.apps.NotificationsConfig",
    "dashboard.apps.DashboardConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "notifications.context_processors.notification_context",
            ],
        },
    },
]

if DATABASE_URL:
    DATABASES = {"default": database_config_from_url(DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

REDIS_URL = os.getenv("REDIS_URL", "").strip()
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "IGNORE_EXCEPTIONS": True,
            },
            "KEY_PREFIX": "analytics-platform",
        }
    }
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL], "capacity": 1500, "expiry": 30},
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "analytics-platform-local",
        }
    }
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL or "memory://")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL or "cache+memory://")

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 1_048_576
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1_000
FILE_UPLOAD_MAX_MEMORY_SIZE = 5_242_880

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:overview"
LOGOUT_REDIRECT_URL = "accounts:login"

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "monitoring@localhost")

SLOW_REQUEST_THRESHOLD = int(os.getenv("SLOW_REQUEST_THRESHOLD", "1000"))
EVENT_RETENTION_DAYS = int(os.getenv("EVENT_RETENTION_DAYS", "90"))
ANALYTICS_CACHE_TTL = int(os.getenv("ANALYTICS_CACHE_TTL", "30"))
ERROR_SPIKE_THRESHOLD = int(os.getenv("ERROR_SPIKE_THRESHOLD", "5"))
ERROR_SPIKE_MULTIPLIER = float(os.getenv("ERROR_SPIKE_MULTIPLIER", "3"))

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "api.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "api.exceptions.api_exception_handler",
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%S.%fZ",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Real-time Analytics & Monitoring API",
    "DESCRIPTION": "Authenticated project analytics and API-key event ingestion.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "{levelname} {asctime} {name} {message}", "style": "{"}
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "standard"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}
