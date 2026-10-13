"""Deduplicated normalized carrier lifecycle events."""

from django.db import models
from django.utils.translation import gettext_lazy as _
from .base import VoIPModel


class PhoneCallEvent(VoIPModel):
    """Retain state transitions without storing raw webhook payloads or secrets."""

    call = models.ForeignKey(
        "bloomerp.PhoneCall",
        verbose_name=_("Call"),
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_id = models.CharField(_("Event identifier"), max_length=255)
    status = models.CharField(_("Status"), max_length=24)
    occurred_at = models.DateTimeField(_("Occurred at"))

    class Meta(VoIPModel.Meta):
        db_table = "bloomerp_phone_call_event"
        constraints = [
            models.UniqueConstraint(
                fields=["call", "event_id"], name="phone_call_event_unique"
            )
        ]

    def __str__(self) -> str:
        """Return the normalized lifecycle status."""
        return self.status
