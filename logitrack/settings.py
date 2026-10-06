"""Django settings for logitrack project."""

from pathlib import Path
import os
import sys

import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

load_dotenv(BASE_DIR := Path(__file__).resolve().parent.parent / ".env")

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
DEBUG = os.environ.get("DEBUG", "1") == "1"
default_hosts = ["localhost", "127.0.0.1", "testserver", "[::1]"]
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", ",".join(default_hosts)).split(",") if os.environ.get("ALLOWED_HOSTS") else default_hosts

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "storages",
    "shipments",
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

ROOT_URLCONF = "logitrack.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "logitrack.wsgi.application"

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///" + str(BASE_DIR / "db.sqlite3"))
DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
WHITENOISE_MANIFEST_STRICT = False

# Media & Cloud Object Storage Configuration (AWS S3 & Cloudflare R2 compatibility)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

USE_S3 = os.environ.get("USE_S3", "0") == "1" or bool(os.environ.get("AWS_STORAGE_BUCKET_NAME"))
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "")
AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", "auto")
AWS_S3_ENDPOINT_URL = os.environ.get("AWS_S3_ENDPOINT_URL", "")

if not DEBUG and not USE_S3:
    raise ImproperlyConfigured(
        "Production media storage must use S3-compatible object storage. "
        "Set USE_S3=1 and configure AWS_STORAGE_BUCKET_NAME."
    )
if USE_S3 and not AWS_STORAGE_BUCKET_NAME:
    raise ImproperlyConfigured("AWS_STORAGE_BUCKET_NAME is required when USE_S3=1.")
if bool(AWS_ACCESS_KEY_ID) != bool(AWS_SECRET_ACCESS_KEY):
    raise ImproperlyConfigured("Set both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, or neither.")
if AWS_S3_ENDPOINT_URL and not (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY):
    raise ImproperlyConfigured("S3-compatible custom endpoints require both AWS access keys.")

if USE_S3:
    s3_options = {
        "bucket_name": AWS_STORAGE_BUCKET_NAME,
        "region_name": AWS_S3_REGION_NAME,
        "endpoint_url": AWS_S3_ENDPOINT_URL or None,
        "default_acl": None,
        "file_overwrite": False,
        "querystring_auth": True,
        "querystring_expire": 300,
        "signature_version": "s3v4",
    }
    if AWS_ACCESS_KEY_ID:
        s3_options["access_key"] = AWS_ACCESS_KEY_ID
        s3_options["secret_key"] = AWS_SECRET_ACCESS_KEY

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": s3_options,
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }

IS_TESTING = "test" in sys.argv
if IS_TESTING:
    STORAGES["staticfiles"] = {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    }

# Celery & Redis Configuration
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_TASK_ALWAYS_EAGER = IS_TESTING or (os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1")
CELERY_TASK_EAGER_PROPAGATES = True

# Cache configuration (for django-ratelimit and general caching)
if REDIS_URL and not IS_TESTING and os.environ.get("REDIS_CACHE_ENABLED", "0") == "1":
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "logitrack-inmemory-cache",
        }
    }

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "hello@logitrack.local")
LOGIN_URL = "/login/"

SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
