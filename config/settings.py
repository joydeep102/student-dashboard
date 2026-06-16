"""
Django settings for the Student Dashboard portal.

Generated with Django 6.0 and customized for:
  - Admin-created student accounts (custom user model)
  - Live classes via auto-generated Google Meet links
  - Recorded lessons played through a branded in-portal player (no raw YouTube UI)
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Core / security
# ---------------------------------------------------------------------------
# Read secrets from the environment in production; fall back to a dev value.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-_+v2ztwlj@6&8zp1dyaik_3@1bulb=2-o-hh567^=s5v&y7urv",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() == "true"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

# Behind an HTTPS reverse proxy (nginx / Traefik / Cloudflare), trust the
# forwarded scheme so Django knows the request was secure (CSRF + OAuth).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Local apps
    "accounts",
    "courses",
    "classroom",
    "trainers",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves static files in production (no separate web server needed).
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database  (SQLite for dev; switch via DATABASE_URL-style env in production)
# ---------------------------------------------------------------------------
# Use PostgreSQL when POSTGRES_DB is provided (Docker/production); otherwise the
# zero-config SQLite file for local development.
if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "db"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "courses:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Google Meet / Calendar integration
# ---------------------------------------------------------------------------
# Path to an OAuth client-secret JSON (Desktop or Web app) downloaded from the
# Google Cloud Console with the Calendar API enabled. A token is cached after
# the first authorization so Meet links can be created unattended.
GOOGLE_OAUTH_CLIENT_SECRET_FILE = os.environ.get(
    "GOOGLE_OAUTH_CLIENT_SECRET_FILE", str(BASE_DIR / "secrets" / "client_secret.json")
)
GOOGLE_OAUTH_TOKEN_FILE = os.environ.get(
    "GOOGLE_OAUTH_TOKEN_FILE", str(BASE_DIR / "secrets" / "token.json")
)
# Calendar to create class events on ("primary" = the authorizing account's calendar)
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

# Separate cached token for YouTube uploads (youtube.upload scope). Authorize
# once with:  python manage.py youtube_auth
GOOGLE_YOUTUBE_TOKEN_FILE = os.environ.get(
    "GOOGLE_YOUTUBE_TOKEN_FILE", str(BASE_DIR / "secrets" / "youtube_token.json")
)
# Per-trainer cached OAuth tokens (one JSON per user id). When a batch's
# trainer has connected their own Google, that batch's Meet events are created
# on the trainer's calendar so the trainer is the meeting host.
GOOGLE_TRAINER_TOKEN_DIR = os.environ.get(
    "GOOGLE_TRAINER_TOKEN_DIR", str(BASE_DIR / "secrets" / "trainer_tokens")
)
# Default privacy for trainer videos uploaded to YouTube (kept off public search).
YOUTUBE_UPLOAD_PRIVACY = os.environ.get("YOUTUBE_UPLOAD_PRIVACY", "unlisted")

# ---------------------------------------------------------------------------
# "Sign in with Google" — web OAuth login for portal users
# ---------------------------------------------------------------------------
# Credentials come from env vars, or a git-ignored secrets/google_login.json.
# Login matches the Google email to an EXISTING active user (admin-created
# accounts only); it never auto-creates accounts.
import json as _json

_glogin = {}
_glf = BASE_DIR / "secrets" / "google_login.json"
if _glf.exists():
    try:
        _glogin = _json.loads(_glf.read_text(encoding="utf-8"))
    except Exception:
        _glogin = {}

GOOGLE_LOGIN_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", _glogin.get("client_id", ""))
GOOGLE_LOGIN_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", _glogin.get("client_secret", ""))
GOOGLE_LOGIN_REDIRECT_URI = os.environ.get(
    "GOOGLE_LOGIN_REDIRECT_URI",
    _glogin.get("redirect_uri", "http://127.0.0.1:8000/accounts/google/callback/"),
)
GOOGLE_LOGIN_ENABLED = bool(GOOGLE_LOGIN_CLIENT_ID and GOOGLE_LOGIN_CLIENT_SECRET)
