"""
Mock external service settings.

This is a completely separate Django project from the UTTT platform.
It uses SQLite so no PostgreSQL configuration is needed.
It communicates with UTTT exclusively through HTTP.
"""
import os
import sys
from pathlib import Path

# Ensure decouple reads mock_service/.env, not the repo-root .env
MOCK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MOCK_DIR))

from decouple import AutoConfig, Csv

# Point decouple at mock_service/.env
config = AutoConfig(search_path=str(MOCK_DIR))

BASE_DIR = MOCK_DIR

SECRET_KEY = config('MOCK_SECRET_KEY', default='mock-service-dev-secret-not-for-production')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'rest_framework',
    'runner',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {'context_processors': [
            'django.template.context_processors.request',
        ]},
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'mock.sqlite3',
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = False
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': ['rest_framework.parsers.JSONParser'],
}

# ---------------------------------------------------------------------------
# Mock service configuration
# ---------------------------------------------------------------------------

# API key that UTTT must send in X-Api-Key when calling this service
MOCK_API_KEY = config('MOCK_API_KEY', default='')

# Allowed UTTT callback base URLs (comma-separated).
# The mock service only POSTs callbacks to URLs starting with one of these.
# Prevents the service from sending callbacks to arbitrary URLs.
ALLOWED_CALLBACK_URLS = config(
    'ALLOWED_CALLBACK_URLS',
    cast=Csv(),
    default='http://127.0.0.1:8000',
)

# Delay in seconds before TC002 reports completion
TC002_DELAY_SECONDS = config('TC002_DELAY_SECONDS', default=3.0, cast=float)

# Retry settings for outbound callbacks
CALLBACK_MAX_RETRIES = config('CALLBACK_MAX_RETRIES', default=5, cast=int)
CALLBACK_HTTP_TIMEOUT_SECONDS = config('CALLBACK_HTTP_TIMEOUT_SECONDS', default=10, cast=int)

# API key this service sends in X-Callback-Api-Key when posting callbacks to UTTT.
# Must match the PRODUCT_DEMO_CALLBACK_SECRET value in the UTTT .env.
UTTT_CALLBACK_API_KEY = config('UTTT_CALLBACK_API_KEY', default='')

# Worker poll interval
MOCK_WORKER_POLL_INTERVAL_SECONDS = config('MOCK_WORKER_POLL_INTERVAL_SECONDS', default=2, cast=int)
