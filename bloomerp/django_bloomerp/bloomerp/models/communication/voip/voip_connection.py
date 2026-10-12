"""Configured carrier accounts and encrypted server-side credentials."""

import json
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from bloomerp.communication.utils.crypto import (
    decrypt_email_secret,
    encrypt_email_secret,
    is_encrypted_email_secret,
)
from .base import VoIPModel


def voip_provider_choices() -> list[tuple[str, str]]:
    """Resolve registered carrier choices after application loading."""
    from bloomerp.communication.builtins.voip.registry import VOIP_PROVIDER_REGISTRY

    return [(p.key, p.display_name) for p in VOIP_PROVIDER_REGISTRY.values()]


class VoIPConnection(VoIPModel):
    """Own an independently configured carrier account and synchronization state."""

    immutable_fields = ("provider", "external_account_id")
    name = models.CharField(_("Name"), max_length=255)
    provider = models.CharField(
        _("Provider"), max_length=32, choices=voip_provider_choices
    )
    external_account_id = models.CharField(_("Account identifier"), max_length=255)
    status = models.CharField(
        _("Status"),
        max_length=16,
        default="draft",
        choices=[
            ("draft", _("Draft")),
            ("active", _("Active")),
            ("disabled", _("Disabled")),
            ("error", _("Error")),
        ],
    )
    settings = models.JSONField(_("Configuration"), default=dict, blank=True)
    credentials = models.TextField(_("Credentials"), editable=False, blank=True)
    sync_enabled = models.BooleanField(_("Synchronize history"), default=True)
    last_synced_at = models.DateTimeField(_("Last synchronized"), null=True, blank=True)
    validated_at = models.DateTimeField(_("Validated at"), null=True, blank=True)

    class Meta(VoIPModel.Meta):
        db_table = "bloomerp_voip_connection"
        verbose_name = _("VoIP connection")
        verbose_name_plural = _("VoIP connections")

    def __str__(self) -> str:
        """Return the configured account label without exposing secrets."""
        return self.name

    def set_credentials(self, credentials: dict[str, str]) -> None:
        """Encrypt carrier credentials using the communications encryption key."""
        if not all(
            isinstance(k, str) and isinstance(v, str) for k, v in credentials.items()
        ):
            raise ValidationError(_("Invalid credentials."))
        self.credentials = encrypt_email_secret(json.dumps(credentials))

    def get_credentials(self) -> dict[str, str]:
        """Decrypt credentials only for trusted server-side adapter construction."""
        return (
            json.loads(decrypt_email_secret(self.credentials))
            if self.credentials
            else {}
        )

    def clean(self) -> None:
        """Reject plaintext credentials and secrets supplied as ordinary settings."""
        super().clean()
        if self.credentials and not is_encrypted_email_secret(self.credentials):
            raise ValidationError(
                {"credentials": _("Use encrypted credential storage.")}
            )
        from bloomerp.communication.builtins.voip.registry import VOIP_PROVIDER_REGISTRY

        provider = VOIP_PROVIDER_REGISTRY.get(self.provider)
        if provider:
            secret_names = {
                name
                for name, field in provider.config_schema.model_json_schema()[
                    "properties"
                ].items()
                if field.get("writeOnly")
            }
            if secret_names.intersection(self.settings):
                raise ValidationError(
                    {"settings": _("Secrets must be stored as encrypted credentials.")}
                )
