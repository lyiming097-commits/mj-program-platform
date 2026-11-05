from datetime import timedelta
from pathlib import Path
import os

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(file_path: Path) -> None:
    if not file_path.exists():
        return
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(BASE_DIR / ".env")

# Optional paid company lookup; the credential is mounted only in auth-backend.
BUSINESS_REGISTRY_APPCODE = os.getenv("BUSINESS_REGISTRY_APPCODE_SECRET", "").strip()


def get_database_config() -> dict:
    engine = os.getenv("DB_ENGINE", "sqlite").strip().lower()
    if engine in {"postgres", "postgresql", "django.db.backends.postgresql"}:
        db_host = os.getenv("DB_HOST", "localhost").strip()
        db_port = os.getenv("DB_PORT", "5432").strip()

        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "auth_db"),
            "USER": os.getenv("DB_USER", "auth_user"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": db_host,
            "PORT": db_port,
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60") or "60"),
        }

    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / os.getenv("SQLITE_NAME", "db.sqlite3"),
    }

DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
AUTH_RUNTIME_ROLE = os.getenv("AUTH_RUNTIME_ROLE", "web").strip().lower() or "web"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-secret-key")
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if host.strip()]
for internal_host in os.getenv("AUTH_INTERNAL_ALLOWED_HOSTS", "auth-backend").split(","):
    normalized_host = internal_host.strip()
    if normalized_host and normalized_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(normalized_host)
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "identity_api",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "identity_api.internal.ApiResponseContractMiddleware",
    "identity_api.internal.InternalApiGovernanceMiddleware",
    "identity_api.security.SameOriginWriteMiddleware",
    "identity_api.auth.middleware.AuthTokenMiddleware",
    "identity_api.org.snapshot.OrganizationSnapshotMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mj_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "mj_backend.wsgi.application"
ASGI_APPLICATION = "mj_backend.asgi.application"

DATABASES = {
    "default": get_database_config(),
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv("AUTH_CACHE_REDIS_URL", "redis://redis:6379/2"),
        "TIMEOUT": 300,
    }
}

CELERY_BROKER_URL = os.getenv("AUTH_CELERY_BROKER_URL", "redis://redis:6379/1")
CELERY_RESULT_BACKEND = None
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv("AUTH_SYNC_SOFT_TIME_LIMIT_SECONDS", "1200") or "1200")
CELERY_TASK_TIME_LIMIT = int(os.getenv("AUTH_SYNC_TIME_LIMIT_SECONDS", "1260") or "1260")
CELERY_TASK_ROUTES = {
    "auth.send_robot_messages": {"queue": "auth_robot_messages"},
    "auth.sync_organization_contacts": {"queue": "auth_sync"},
    "auth.schedule_organization_sync": {"queue": "auth_sync"},
    "auth.prune_expired_sessions": {"queue": "auth_sync"},
}
CELERY_BEAT_SCHEDULE = {
    "auth-periodic-organization-sync": {
        "task": "auth.schedule_organization_sync",
        "schedule": timedelta(
            seconds=max(300, int(os.getenv("AUTH_ORG_SYNC_INTERVAL_SECONDS", "900") or "900")),
        ),
        "options": {"queue": "auth_sync"},
    },
    "auth-prune-expired-sessions": {
        "task": "auth.prune_expired_sessions",
        "schedule": timedelta(hours=1),
        "options": {"queue": "auth_sync"},
    },
}

if (
    os.getenv("DJANGO_DISABLE_LOCAL_APP_MIGRATIONS", "0") == "1"
    and os.getenv("AUTH_USE_DJANGO_MIGRATIONS", "1") != "1"
):
    MIGRATION_MODULES = {
        "identity_api": None,
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = Path(os.getenv("STATIC_ROOT", BASE_DIR / "staticfiles"))
MEDIA_URL = "/images/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "images"))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL_ORIGINS", "1" if DEBUG else "0") == "1" and not CORS_ALLOWED_ORIGINS
CORS_EXPOSE_HEADERS = [
    "X-Auth-Token-Expires-At",
    "X-Auth-Token-Expires-In",
    "X-Request-Id",
    "X-Organization-Revision",
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True


def _truthy_environment(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _validate_production_security_configuration() -> None:
    if DEBUG:
        return
    if len(SECRET_KEY) < 32 or SECRET_KEY in {"dev-only-secret-key", "auth-django-change-me"}:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a non-default secret of at least 32 characters")
    if "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must list explicit production hosts")

    if AUTH_RUNTIME_ROLE != "web":
        return

    token_secret = os.getenv("AUTH_TOKEN_SECRET", "").strip()
    if len(token_secret) < 32 or token_secret == "mj-program-change-me":
        raise ImproperlyConfigured("AUTH_TOKEN_SECRET must be a non-default secret of at least 32 characters")
    if token_secret == SECRET_KEY:
        raise ImproperlyConfigured("AUTH_TOKEN_SECRET must be different from DJANGO_SECRET_KEY")
    if _truthy_environment("AUTH_DEV_LOGIN_ENABLED") or _truthy_environment("AUTH_DEV_LOGIN_ALLOW_REMOTE"):
        raise ImproperlyConfigured("Development login must be disabled in production")
    if not _truthy_environment("AUTH_COOKIE_SECURE"):
        raise ImproperlyConfigured("AUTH_COOKIE_SECURE must be enabled in production")
    if not os.getenv("DINGTALK_JSAPI_ALLOWED_ORIGINS", "").strip():
        raise ImproperlyConfigured("DINGTALK_JSAPI_ALLOWED_ORIGINS must be configured in production")


_validate_production_security_configuration()
