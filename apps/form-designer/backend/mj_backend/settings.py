import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
def secret(name, default=''):
    path = os.getenv(name + '_FILE')
    return Path(path).read_text(encoding='utf-8').strip() if path else os.getenv(name, default)
SECRET_KEY = secret('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError('DJANGO_SECRET_KEY or DJANGO_SECRET_KEY_FILE is required')
DEBUG = False
ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
CSRF_TRUSTED_ORIGINS = [x for x in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if x]
INSTALLED_APPS = ['form_designer_api']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'form_designer_api.platform.SameOriginWriteMiddleware',
    'form_designer_api.platform.AuthTokenMiddleware',
    'form_designer_api.organization.SnapshotMiddleware',
]
ROOT_URLCONF = 'mj_backend.urls'
WSGI_APPLICATION = 'mj_backend.wsgi.application'
ASGI_APPLICATION = 'mj_backend.asgi.application'
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': os.getenv('DB_NAME', 'form_designer_db'),
    'USER': os.getenv('DB_USER', 'form_designer_user'),
    'PASSWORD': secret('DB_PASSWORD'),
    'HOST': os.getenv('DB_HOST', '127.0.0.1'),
    'PORT': os.getenv('DB_PORT', '5432'),
    'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '60')),
    'TEST': {'NAME': os.getenv('DB_TEST_NAME', 'form_designer_test')},
}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_TZ = True
APPEND_SLASH = False
DATA_UPLOAD_MAX_MEMORY_SIZE = 2097152
