from __future__ import annotations

import importlib.util

from django.conf import settings
from django.urls import NoReverseMatch, reverse

from bloomerp.config.definition import (
    BloomerpAuthSettings,
    BloomerpConfig,
    InteractiveAuthSettings,
    SocialProviderSettings,
)


SOCIAL_PROVIDER_LABELS = {
    "apple": "Apple",
    "facebook": "Facebook",
    "github": "GitHub",
    "google": "Google",
    "linkedin": "LinkedIn",
    "microsoft": "Microsoft",
}


def get_bloomerp_config() -> BloomerpConfig:
    config = getattr(settings, "BLOOMERP_CONFIG", None)
    if isinstance(config, BloomerpConfig):
        return config
    return BloomerpConfig()


def get_auth_settings() -> BloomerpAuthSettings:
    return get_bloomerp_config().auth


def get_interactive_auth_settings() -> InteractiveAuthSettings:
    return get_auth_settings().interactive


def allauth_is_installed() -> bool:
    return importlib.util.find_spec("allauth") is not None


def allauth_is_enabled() -> bool:
    interactive = get_interactive_auth_settings()
    return bool(interactive.use_allauth and allauth_is_installed())


def get_login_identifier() -> str:
    return get_interactive_auth_settings().login_identifier


def registration_is_enabled() -> bool:
    interactive = get_interactive_auth_settings()
    return bool(interactive.signup_enabled)


def get_login_field_label() -> str:
    return "Email" if get_login_identifier() == "email" else "Username"


def get_login_help_text() -> str:
    return (
        "Enter your email address and password to login"
        if get_login_identifier() == "email"
        else "Enter your username and password to login"
    )


def get_social_login_providers() -> list[dict[str, object]]:
    interactive = get_interactive_auth_settings()
    providers: list[dict[str, object]] = []

    for provider in interactive.social_providers:
        if not provider.enabled:
            continue

        provider_id = provider.provider.strip().lower()
        if not provider_id:
            continue

        provider_data: dict[str, object] = {
            "id": provider_id,
            "name": provider.label or SOCIAL_PROVIDER_LABELS.get(provider_id, provider_id.replace("_", " ").title()),
            "login_url": None,
            "is_available": False,
            "allow_login": provider.allow_login,
            "allow_signup": provider.allow_signup,
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
        }

        if provider.allow_login and allauth_is_enabled():
            try:
                provider_data["login_url"] = reverse(
                    "socialaccount_login",
                    kwargs={"provider": provider_id},
                )
                provider_data["is_available"] = True
            except NoReverseMatch:
                provider_data["is_available"] = False

        providers.append(provider_data)

    return providers