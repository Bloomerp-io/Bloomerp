from __future__ import annotations

import importlib.util


def _has_allauth() -> bool:
    return importlib.util.find_spec("allauth") is not None


BLOOMERP_APPS = [
    "bloomerp",
    "django_htmx",
    "crispy_forms",
    "rest_framework",
    "django_filters",
    "tailwind",
    "django_cotton",
    "django_browser_reload",
    "crispy_tailwind",
]

if _has_allauth():
    BLOOMERP_APPS += [
        "django.contrib.sites",
        "allauth",
        "allauth.account",
        "allauth.socialaccount",
    ]

BLOOMERP_MIDDLEWARE = [
    "bloomerp.middleware.HTMXPermissionDeniedMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django_browser_reload.middleware.BrowserReloadMiddleware",
]

BLOOMERP_USER_MODEL = "bloomerp.User"

BLOOMERP_AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

if _has_allauth():
    BLOOMERP_AUTHENTICATION_BACKENDS.append(
        "allauth.account.auth_backends.AuthenticationBackend"
    )

BLOOMERP_SITE_ID = 1
BLOOMERP_ALLAUTH_AVAILABLE = _has_allauth()
