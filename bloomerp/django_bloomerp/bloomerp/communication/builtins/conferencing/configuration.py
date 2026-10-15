"""Resolve conferencing settings without relying on SDK environment defaults."""

from django.core.exceptions import ImproperlyConfigured

from bloomerp.config.definition import ConferencingSettings, get_bloomerp_config


def get_conferencing_settings() -> ConferencingSettings:
    """Return a validated configuration snapshot or reject disabled conferencing."""
    configured = get_bloomerp_config().conferencing
    # model_dump excludes credentials, so reconstruct the validated snapshot explicitly.
    resolved = ConferencingSettings(
        enabled=configured.enabled,
        api_url=configured.api_url,
        public_url=configured.public_url,
        api_key=configured.api_key,
        api_secret=configured.api_secret,
        join_token_ttl_seconds=configured.join_token_ttl_seconds,
        api_timeout_seconds=configured.api_timeout_seconds,
        max_participants=configured.max_participants,
    )
    if not resolved.enabled:
        raise ImproperlyConfigured("Conferencing is disabled for this instance.")
    return resolved
