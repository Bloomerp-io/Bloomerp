"""Synchronized carrier numbers with locally owned labels and assignments."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator
from .base import VoIPModel
from django.utils.translation import gettext_noop
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models.definition import (
    BloomerpModelConfig,
    get_default_dataview_actions,
    ApiSettings,
    ActivityLogSettings,
    DetailViewSettings,
    ModelViewSettings,
    FieldLayout,
    LayoutRow,
    LayoutItem,
)


class VoIPNumber(VoIPModel):
    """Represent a carrier line available to its assigned active staff."""

    bloomerp_config = BloomerpModelConfig(
        module="communication",
        api_settings=ApiSettings(enable_auto_generation=False),
        activity_log_settings=ActivityLogSettings(enabled=False),
        model_view_settings=ModelViewSettings(
            skip_views=["add"],
            dataview_actions=get_default_dataview_actions(skip=["add"]),
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("Phone numbers"),
                    display_fields=[
                        "name",
                        "number",
                        "connection",
                        "is_active",
                        "supports_sms",
                        "supports_voice",
                        "assigned_users",
                    ],
                    sort_field="number",
                )
            ],
        ),
        detail_view_settings=DetailViewSettings(
            layouts=[
                FieldLayout(
                    name=gettext_noop("Phone number"),
                    rows=[
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Business line"),
                            items=[
                                LayoutItem(id=field)
                                for field in (
                                    "name",
                                    "number",
                                    "connection",
                                    "is_active",
                                )
                            ],
                        ),
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Capabilities"),
                            items=[
                                LayoutItem(id=field)
                                for field in ("supports_sms", "supports_voice")
                            ],
                        ),
                        LayoutRow(
                            columns=1,
                            title=gettext_noop("Access"),
                            items=[LayoutItem(id="assigned_users")],
                        ),
                    ],
                )
            ],
            skip_views=["files", "document_templates"],
        ),
    )

    immutable_fields = ("connection_id", "number", "provider_number_id")
    connection = models.ForeignKey(
        "bloomerp.VoIPConnection",
        verbose_name=_("Connection"),
        on_delete=models.PROTECT,
        related_name="numbers",
    )
    number = models.CharField(
        _("Phone number"),
        max_length=16,
        validators=[
            RegexValidator(
                r"^\+[1-9]\d{1,14}$", _("Enter an international phone number.")
            )
        ],
    )
    provider_number_id = models.CharField(
        _("Provider number identifier"), max_length=255
    )
    name = models.CharField(_("Label"), max_length=255, blank=True)
    is_active = models.BooleanField(_("Active"), default=True)
    supports_sms = models.BooleanField(_("SMS enabled"), default=False)
    supports_voice = models.BooleanField(_("Voice enabled"), default=False)
    assigned_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Assigned staff"),
        blank=True,
        related_name="voip_numbers",
    )

    class Meta(VoIPModel.Meta):
        db_table = "bloomerp_voip_number"
        verbose_name = _("VoIP number")
        verbose_name_plural = _("VoIP numbers")
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "provider_number_id"],
                name="voip_number_provider_unique",
            ),
            models.UniqueConstraint(
                fields=["connection", "number"], name="voip_number_address_unique"
            ),
        ]

    def __str__(self) -> str:
        """Display the locally configured label alongside the actual line."""
        return f"{self.name} · {self.number}" if self.name else self.number
