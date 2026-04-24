from __future__ import annotations

import importlib.util
import os

from django.conf import settings

from bloomerp.config.definition import BloomerpConfig, SocialProviderSettings


def _has_allauth() -> bool:
    return importlib.util.find_spec("allauth") is not None


def _get_bloomerp_config() -> BloomerpConfig:
    config = getattr(settings, "BLOOMERP_CONFIG", None)
    if isinstance(config, BloomerpConfig):
        return config
    return BloomerpConfig()


def _resolve_config_value(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("env:"):
        return os.environ.get(value.removeprefix("env:")) or None
    return value


def _enabled_social_providers() -> list[SocialProviderSettings]:
    config = _get_bloomerp_config()
    interactive = config.auth.interactive
    if not interactive.use_allauth:
        return []
    return [
        provider
        for provider in interactive.social_providers
        if provider.enabled and provider.provider.strip()
    ]


def get_bloomerp_social_provider_apps() -> list[str]:
    if not _has_allauth():
        return []
    return [
        f"allauth.socialaccount.providers.{provider.provider.strip().lower()}"
        for provider in _enabled_social_providers()
    ]


def get_bloomerp_socialaccount_providers() -> dict[str, dict]:
    providers: dict[str, dict] = {}

    for provider in _enabled_social_providers():
        provider_id = provider.provider.strip().lower()
        client_id = _resolve_config_value(provider.client_id)
        client_secret = _resolve_config_value(provider.client_secret)

        provider_settings: dict[str, object] = {}
        if client_id and client_secret:
            provider_settings["APPS"] = [
                {
                    "client_id": client_id,
                    "secret": client_secret,
                    "key": "",
                }
            ]

        if provider.scopes:
            provider_settings["SCOPE"] = provider.scopes

        if provider_id == "google":
            provider_settings.setdefault("AUTH_PARAMS", {"access_type": "online"})
            provider_settings.setdefault("OAUTH_PKCE_ENABLED", True)
            provider_settings.setdefault("VERIFIED_EMAIL", True)

        providers[provider_id] = provider_settings

    return providers


def configure_bloomerp_allauth_settings() -> None:
    if not _has_allauth():
        return

    config = _get_bloomerp_config()
    interactive = config.auth.interactive
    if not interactive.use_allauth:
        return

    login_methods = {"email"} if interactive.login_identifier == "email" else {"username"}
    signup_fields = (
        ["email*", "password1*", "password2*"]
        if interactive.login_identifier == "email"
        else ["username*", "email", "password1*", "password2*"]
    )

    settings.SITE_ID = getattr(settings, "SITE_ID", BLOOMERP_SITE_ID)
    settings.ACCOUNT_LOGIN_METHODS = getattr(
        settings,
        "ACCOUNT_LOGIN_METHODS",
        login_methods,
    )
    settings.ACCOUNT_SIGNUP_FIELDS = getattr(
        settings,
        "ACCOUNT_SIGNUP_FIELDS",
        signup_fields,
    )
    settings.ACCOUNT_EMAIL_VERIFICATION = getattr(
        settings,
        "ACCOUNT_EMAIL_VERIFICATION",
        interactive.email_verification,
    )
    settings.ACCOUNT_LOGOUT_ON_GET = getattr(settings, "ACCOUNT_LOGOUT_ON_GET", True)
    settings.ACCOUNT_AUTHENTICATED_LOGIN_REDIRECTS = getattr(
        settings,
        "ACCOUNT_AUTHENTICATED_LOGIN_REDIRECTS",
        True,
    )
    settings.SOCIALACCOUNT_AUTO_SIGNUP = getattr(
        settings,
        "SOCIALACCOUNT_AUTO_SIGNUP",
        interactive.signup_enabled,
    )
    settings.SOCIALACCOUNT_LOGIN_ON_GET = getattr(
        settings,
        "SOCIALACCOUNT_LOGIN_ON_GET",
        True,
    )
    settings.SOCIALACCOUNT_PROVIDERS = get_bloomerp_socialaccount_providers()


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
    BLOOMERP_APPS += get_bloomerp_social_provider_apps()

BLOOMERP_MIDDLEWARE = [
    "bloomerp.middleware.HTMXPermissionDeniedMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django_browser_reload.middleware.BrowserReloadMiddleware",
]

if _has_allauth():
    BLOOMERP_MIDDLEWARE.append("allauth.account.middleware.AccountMiddleware")

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
