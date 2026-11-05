import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-after-sales-secret")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [value.strip() for value in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if value.strip()]
CSRF_TRUSTED_ORIGINS = [value.strip() for value in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if value.strip()]
CORS_ALLOWED_ORIGINS = [value.strip() for value in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if value.strip()]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "after_sales_api",
]
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "after_sales_api.platform.SameOriginWriteMiddleware",
    "after_sales_api.platform.AuthTokenMiddleware",
    "after_sales_api.access_middleware.BusinessAccessMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "mj_backend.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "mj_backend.wsgi.application"
ASGI_APPLICATION = "mj_backend.asgi.application"

if os.getenv("DB_ENGINE", "sqlite").strip().lower() in {"postgres", "postgresql", "django.db.backends.postgresql"}:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "after_sales_db"),
        "USER": os.getenv("DB_USER", "after_sales_user"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("SQLITE_NAME", ":memory:"),
    }}

if os.getenv("DJANGO_DISABLE_LOCAL_APP_MIGRATIONS", "0") == "1":
    MIGRATION_MODULES = {"after_sales_api": None}
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = Path(os.getenv("STATIC_ROOT", BASE_DIR / "staticfiles"))
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "uploads"))
DATA_UPLOAD_MAX_MEMORY_SIZE = 22 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CRM_PROJECT_SOURCE = {
    "BASE_URL": os.getenv("CRM_PROJECT_SOURCE_URL", "http://crm-backend:8000/api/crm/"),
    "TIMEOUT_SECONDS": max(float(os.getenv("CRM_PROJECT_SOURCE_TIMEOUT_SECONDS", "8")), 0.5),
    "SYNC_INTERVAL_SECONDS": int(os.getenv("CRM_PROJECT_SOURCE_SYNC_INTERVAL_SECONDS", "300")),
}
_CACHE_REDIS_URL = os.getenv("REDIS_URL", "").strip()
CACHES = {"default": {
    "BACKEND": "django.core.cache.backends.redis.RedisCache" if _CACHE_REDIS_URL else "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": _CACHE_REDIS_URL or "after-sales-local-cache",
    "KEY_PREFIX": "after-sales",
    "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2} if _CACHE_REDIS_URL else {},
}}
CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL_ORIGINS", "1" if DEBUG else "0") == "1" and not CORS_ALLOWED_ORIGINS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
