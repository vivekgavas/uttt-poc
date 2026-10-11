"""
Django settings for taskapi project.

Credentials and secrets are read from environment variables (or a .env file
in the project root) using python-decouple. See .env.example for all required
variables and instructions for creating your .env file.
"""
from pathlib import Path
from decouple import config, Csv

# Base directory of the repository (the folder containing manage.py)
BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

# Read from .env — required, no default (startup will fail if missing)
SECRET_KEY = config('SECRET_KEY')

# Read from .env — defaults to False (safe for production if .env is missing)
DEBUG = config('DEBUG', default=False, cast=bool)

# Csv() splits a comma-separated string into a Python list
# e.g. "localhost,127.0.0.1" → ['localhost', '127.0.0.1']
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'rest_framework',
    # Our apps
    'uttt',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'taskapi.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'taskapi.wsgi.application'

# ---------------------------------------------------------------------------
# Database — PostgreSQL on localhost:5432
# ---------------------------------------------------------------------------

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='uttt'),
        'USER': config('DB_USER', default='pg'),
        # DB_PASSWORD is required — no default so startup fails clearly if unset
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST', default='127.0.0.1'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# ---------------------------------------------------------------------------
# Password validation (Django admin users)
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_URL = 'static/'

# ---------------------------------------------------------------------------
# Primary key field type
# ---------------------------------------------------------------------------

# BigAutoField uses a 64-bit integer for primary keys (vs 32-bit AutoField)
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    # BrowsableAPIRenderer lets you explore the API in a browser (handy for learning)
    # JSONRenderer returns plain JSON for programmatic clients (curl, Postman, etc.)
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
}

# ---------------------------------------------------------------------------
# UTTT Platform settings
# ---------------------------------------------------------------------------

# API key required in X-Platform-Api-Key header for all platform management endpoints.
# Generate with: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
PLATFORM_API_KEY = config('PLATFORM_API_KEY', default='')

# Base URL of this UTTT platform, used by the worker to build callback URLs.
# Must be reachable from the external test service (mock service on port 8001).
UTTT_BASE_URL = config('UTTT_BASE_URL', default='http://127.0.0.1:8000')

# How long (seconds) to wait for a terminal callback before marking TIMED_OUT.
EXECUTION_TIMEOUT_SECONDS = config('EXECUTION_TIMEOUT_SECONDS', default=30, cast=int)

# How often the UTTT worker polls for pending work (seconds).
WORKER_POLL_INTERVAL_SECONDS = config('WORKER_POLL_INTERVAL_SECONDS', default=3, cast=int)

# Maximum number of dispatch attempts before a dispatch is marked FAILED.
WORKER_MAX_DISPATCH_RETRIES = config('WORKER_MAX_DISPATCH_RETRIES', default=3, cast=int)

# HTTP timeout for outbound dispatch calls to the external service (seconds).
WORKER_HTTP_TIMEOUT_SECONDS = config('WORKER_HTTP_TIMEOUT_SECONDS', default=10, cast=int)

# A SENDING dispatch older than this many seconds is assumed to be from a crashed
# worker and is reset to UNCERTAIN so it can be retried.
WORKER_STALE_DISPATCH_SECONDS = config('WORKER_STALE_DISPATCH_SECONDS', default=60, cast=int)
