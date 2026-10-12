"""Provider-neutral messaging persistence."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import IMModel


def im_provider_choices() -> list[tuple[str, str]]:
    """Resolve provider registration only after Django finishes loading models."""
    from bloomerp.communication.builtins.instant_messaging.registry import (
        IM_PROVIDER_REGISTRY,
    )

    return [
        (provider.key, provider.display_name)
        for provider in IM_PROVIDER_REGISTRY.values()
        if not provider.internal
    ]


class IMConnection(IMModel):
    """Own a provider account, its endpoints and provider-scoped identities."""

    immutable_fields = ("provider",)
    name = models.CharField(max_length=255)
    provider = models.CharField(max_length=32, choices=im_provider_choices)
    status = models.CharField(
        max_length=16,
        choices=[
            ("draft", _("Draft")),
            ("active", _("Active")),
            ("disabled", _("Disabled")),
            ("error", _("Error")),
        ],
        default="draft",
    )
    external_account_id = models.CharField(max_length=255, blank=True)
    settings = models.JSONField(
        default=dict, blank=True, help_text=_("Non-secret provider settings only.")
    )
    sync_cursor = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta(IMModel.Meta):
        db_table = "bloomerp_im_connection"

    def __str__(self) -> str:
        """Return the configured account label without credentials."""
        return self.name
