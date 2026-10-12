"""Retained call sessions independent of chat messages and carrier accounts."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from .base import VoIPModel


class PhoneCall(VoIPModel):
    """Track one provider call leg and its optional conversation projection."""

    immutable_fields = (
        "connection_id",
        "number_id",
        "conversation_id",
        "from_address",
        "to_address",
    )
    connection = models.ForeignKey(
        "bloomerp.VoIPConnection",
        verbose_name=_("Connection"),
        on_delete=models.PROTECT,
        related_name="calls",
    )
    number = models.ForeignKey(
        "bloomerp.VoIPNumber",
        verbose_name=_("Business number"),
        on_delete=models.PROTECT,
        related_name="calls",
        null=True,
        blank=True,
    )
    conversation = models.ForeignKey(
        "bloomerp.IMConversation",
        verbose_name=_("Conversation"),
        on_delete=models.SET_NULL,
        related_name="phone_calls",
        null=True,
        blank=True,
    )
    provider_call_id = models.CharField(
        _("Provider call identifier"), max_length=255, blank=True
    )
    parent_call_id = models.CharField(
        _("Parent call identifier"), max_length=255, blank=True
    )
    client_id = models.CharField(
        _("Client request identifier"), max_length=255, blank=True
    )
    direction = models.CharField(
        _("Direction"),
        max_length=16,
        choices=[("inbound", _("Incoming")), ("outbound", _("Outgoing"))],
    )
    status = models.CharField(
        _("Status"),
        max_length=24,
        default="pending",
        choices=[
            ("pending", _("Pending")),
            ("queued", _("Queued")),
            ("ringing", _("Ringing")),
            ("in-progress", _("In progress")),
            ("completed", _("Completed")),
            ("busy", _("Busy")),
            ("no-answer", _("Missed")),
            ("canceled", _("Canceled")),
            ("failed", _("Failed")),
        ],
    )
    from_address = models.CharField(_("From"), max_length=255)
    to_address = models.CharField(_("To"), max_length=255)
    started_at = models.DateTimeField(_("Started at"), null=True, blank=True)
    ended_at = models.DateTimeField(_("Ended at"), null=True, blank=True)
    duration = models.PositiveIntegerField(_("Duration in seconds"), default=0)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Handled by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phone_calls",
    )

    class Meta(VoIPModel.Meta):
        db_table = "bloomerp_phone_call"
        verbose_name = _("Phone call")
        verbose_name_plural = _("Phone calls")
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "provider_call_id"],
                condition=~models.Q(provider_call_id=""),
                name="phone_call_provider_unique",
            ),
            models.UniqueConstraint(
                fields=["connection", "client_id"],
                condition=~models.Q(client_id=""),
                name="phone_call_request_unique",
            ),
        ]

    def clean(self) -> None:
        """Reject cross-account line and conversation references."""
        super().clean()
        if self.number_id and self.number.connection_id != self.connection_id:
            raise ValidationError(
                {"number": _("The number belongs to another connection.")}
            )
        if self.conversation_id and self.conversation.voip_number_id != self.number_id:
            raise ValidationError(
                {"conversation": _("The conversation uses another business number.")}
            )

    def __str__(self) -> str:
        """Describe the historical endpoints without fetching provider data."""
        return f"{self.from_address} → {self.to_address}"
