"""Configuration validation outside the model lifecycle scenario abstraction."""

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings
from pydantic import ValidationError

from bloomerp.communication.builtins.conferencing.configuration import (
    get_conferencing_settings,
)
from bloomerp.config.definition import BloomerpConfig, ConferencingSettings


def conferencing_config() -> BloomerpConfig:
    """Build a local configuration with deliberately distinct browser and API URLs."""
    return BloomerpConfig(
        conferencing=ConferencingSettings(
            enabled=True,
            api_url="http://livekit:7880",
            public_url="wss://calls.example.test",
            api_key="instance-key",
            api_secret="instance-secret-at-least-32-characters",
        )
    )


class TestConferencingConfiguration(SimpleTestCase):
    """Validate opt-in configuration and deployment-independent endpoint resolution."""

    @override_settings(BLOOMERP_CONFIG=BloomerpConfig())
    def test_disabled_by_default(self) -> None:
        """Use case: Unconfigured instance. Expected result: no implicit SDK configuration."""
        # 1. Resolve the default configuration.
        with self.assertRaises(ImproperlyConfigured):
            get_conferencing_settings()

    def test_enabled_requires_complete_configuration(self) -> None:
        """Use case: Incomplete configuration. Expected result: fail before SDK use."""
        # 1. Enable conferencing without supplying its endpoints and credentials.
        with self.assertRaises(ValidationError):
            ConferencingSettings(enabled=True)

    def test_relocation_preserves_public_endpoint_and_secret_privacy(self) -> None:
        """Use case: Move LiveKit off the VM. Expected result: only the API URL changes."""
        # 1. Replace the internal Docker address with a remote server.
        config = conferencing_config()
        config.conferencing.api_url = "https://media.example.test"
        with override_settings(BLOOMERP_CONFIG=config):
            resolved = get_conferencing_settings()
        # 2. Verify endpoint independence and exclusion of credentials from dumps.
        self.assertEqual(resolved.api_url, "https://media.example.test")
        self.assertEqual(resolved.public_url, "wss://calls.example.test")
        self.assertNotIn("api_secret", config.model_dump()["conferencing"])
        self.assertNotIn("api_key", config.model_dump()["conferencing"])
        self.assertNotIn("instance-secret", repr(config))

    def test_rejects_invalid_endpoints_and_token_lifetime(self) -> None:
        """Use case: Invalid deployment settings. Expected result: reject unsafe URLs and TTLs."""
        # 1. Check malformed or credential-bearing endpoint values.
        for field, value in [
            ("api_url", "ftp://example.test"),
            ("api_url", "http://key:secret@example.test"),
            ("public_url", "https://example.test"),
            ("public_url", "wss://example.test?token=secret"),
            ("join_token_ttl_seconds", 0),
        ]:
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(ValidationError),
            ):
                ConferencingSettings(**{field: value})
