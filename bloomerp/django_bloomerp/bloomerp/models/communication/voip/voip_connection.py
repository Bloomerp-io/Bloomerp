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
from django.utils.translation import gettext_noop
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models.definition import (
    BloomerpModelConfig,
    DataviewHTMLAction,
    get_default_dataview_actions,
    ApiSettings,
    ActivityLogSettings,
    DetailViewSettings,
    ModelViewSettings,
    FieldLayout,
    LayoutRow,
    LayoutItem,
    ObjectAction,
)
from bloomerp.communication.builtins.voip.actions import (
    can_change_connection,
    can_create_connection,
    synchronize_numbers,
)


def voip_provider_choices() -> list[tuple[str, str]]:
    """Resolve registered carrier choices after application loading."""
    from bloomerp.communication.builtins.voip.registry import VOIP_PROVIDER_REGISTRY

    return [(p.key, p.display_name) for p in VOIP_PROVIDER_REGISTRY.values()]


class VoIPConnection(VoIPModel):
    """Own an independently configured carrier account and synchronization state."""

    bloomerp_config = BloomerpModelConfig(
        module="communication",
        api_settings=ApiSettings(enable_auto_generation=False),
        activity_log_settings=ActivityLogSettings(enabled=False),
        model_view_settings=ModelViewSettings(
            dataview_actions=[
                DataviewHTMLAction(
                    id="add",
                    template_name="models/voip_connection/add.html",
                    should_render_func=can_create_connection,
                ),
                *get_default_dataview_actions(skip=["add"]),
            ],
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("Connections"),
                    display_fields=[
                        "name",
                        "provider",
                        "status",
                        "last_synced_at",
                        "validated_at",
                    ],
                    sort_field="name",
                )
            ],
        ),
        detail_view_settings=DetailViewSettings(
            layouts=[
                FieldLayout(
                    name=gettext_noop("Connection"),
                    rows=[
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Account"),
                            items=[
                                LayoutItem(id=field)
                                for field in (
                                    "name",
                                    "provider",
                                    "external_account_id",
                                    "status",
                                )
                            ],
                        ),
                        LayoutRow(
                            columns=3,
                            title=gettext_noop("Synchronization"),
                            items=[
                                LayoutItem(id=field)
                                for field in (
                                    "sync_enabled",
                                    "last_synced_at",
                                    "validated_at",
                                )
                            ],
                        ),
                    ],
                )
            ],
            skip_views=["files", "document_templates"],
        ),
        object_actions=[
            ObjectAction(
                id="synchronize_numbers",
                label=gettext_noop("Synchronize phone numbers"),
                icon="fa-solid fa-rotate",
                execution_func=synchronize_numbers,
                should_render_func=can_change_connection,
            ),
        ],
    )

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
