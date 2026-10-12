"""Synchronized carrier numbers with locally owned labels and assignments."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator
from .base import VoIPModel


class VoIPNumber(VoIPModel):
    """Represent a carrier line available to its assigned active staff."""

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
