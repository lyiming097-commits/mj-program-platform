from pathlib import Path
import os


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


def get_database_config() -> dict:
    engine = os.getenv("DB_ENGINE", "sqlite").strip().lower()
    if engine in {"postgres", "postgresql", "django.db.backends.postgresql"}:
        db_host = os.getenv("DB_HOST", "localhost").strip()
        db_port = os.getenv("DB_PORT", "5432").strip()

        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "cable_mall_db"),
            "USER": os.getenv("DB_USER", "cable_mall_user"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": db_host,
            "PORT": db_port,
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60") or "60"),
        }

    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / os.getenv("SQLITE_NAME", "db.sqlite3"),
    }

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-secret-key")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if host.strip()]
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "identity_api",
    "cable_mall",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "identity_api.security.SameOriginWriteMiddleware",
    "identity_api.auth.middleware.AuthTokenMiddleware",
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

if os.getenv("DJANGO_DISABLE_LOCAL_APP_MIGRATIONS", "0") == "1":
    MIGRATION_MODULES = {
        "identity_api": None,
        "cable_mall": None,
    }

SERVICE_NAME = os.getenv("SERVICE_NAME", "cable-mall-backend").strip() or "cable-mall-backend"
AUTH_SERVICE_INTROSPECTION_SECRET = os.getenv("AUTH_SERVICE_INTROSPECTION_SECRET", "").strip()
PRODUCT_ARCHIVE_CATALOG = {
    "BASE_URL": os.getenv(
        "PRODUCT_ARCHIVE_CATALOG_URL",
        "http://product-archive-backend:8000/api/internal/product-catalog/",
    ),
    "CABLES_PATH": os.getenv("PRODUCT_ARCHIVE_CATALOG_CABLES_PATH", "cables/"),
    "HEALTH_PATH": os.getenv("PRODUCT_ARCHIVE_CATALOG_HEALTH_PATH", "health/"),
    "TIMEOUT_SECONDS": float(os.getenv("PRODUCT_ARCHIVE_CATALOG_TIMEOUT_SECONDS", "8") or "8"),
    "SYNC_INTERVAL_SECONDS": int(os.getenv("PRODUCT_ARCHIVE_CATALOG_SYNC_INTERVAL_SECONDS", "300") or "300"),
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = Path(os.getenv("STATIC_ROOT", BASE_DIR / "staticfiles"))
MEDIA_URL = os.getenv("CABLE_MALL_MEDIA_URL", "/cable-mall-media/")
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "images"))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL_ORIGINS", "1" if DEBUG else "0") == "1" and not CORS_ALLOWED_ORIGINS
CORS_EXPOSE_HEADERS = [
    "X-Auth-Token-Expires-At",
    "X-Auth-Token-Expires-In",
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
