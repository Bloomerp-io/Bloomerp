import os
from pathlib import Path

from bloomerp.cli.utils import get_project_manifest
from bloomerp.cli.project.marketplace_sources import runtime_installed_apps
from bloomerp.config.settings import (
    BLOOMERP_APPS,
    BLOOMERP_AUTHENTICATION_BACKENDS,
    BLOOMERP_MIDDLEWARE,
    BLOOMERP_SITE_ID,
    BLOOMERP_USER_MODEL,
    REST_FRAMEWORK,
)

BASE_DIR = Path(
    os.environ.get(
        "BLOOMERP_PROJECT_ROOT",
        Path(__file__).resolve().parent.parent.parent.parent,
    )
).resolve()

manifest = get_project_manifest(BASE_DIR)

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "bloomerp",
    *runtime_installed_apps(manifest, BASE_DIR)
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, *BLOOMERP_APPS]))
MIDDLEWARE += BLOOMERP_MIDDLEWARE
AUTHENTICATION_BACKENDS = BLOOMERP_AUTHENTICATION_BACKENDS
AUTH_USER_MODEL = BLOOMERP_USER_MODEL
SITE_ID = BLOOMERP_SITE_ID

CRISPY_ALLOWED_TEMPLATE_PACKS = "tailwind"
CRISPY_TEMPLATE_PACK = "tailwind"

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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
ASGI_APPLICATION = "config.asgi.application"

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "memory://")
CELERY_RESULT_BACKEND = os.environ.get(
    "CELERY_RESULT_BACKEND",
    "cache+memory://",
)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

BLOOMERP_CONFIG = manifest.bloomerp
