"""Deduplication records for verified LiveKit events."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import ConferenceModel


class ConferenceWebhookReceipt(ConferenceModel):
    """Track processing without retaining raw webhook bodies or access tokens."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PROCESSED = "processed", _("Processed")
        IGNORED = "ignored", _("Ignored")
        FAILED = "failed", _("Failed")

    immutable_fields = ("event_id", "event_type", "occurred_at")
    event_id = models.CharField(_("Event ID"), max_length=255, unique=True)
    event_type = models.CharField(_("Event type"), max_length=100)
    occurred_at = models.DateTimeField(_("Occurred at"))
    status = models.CharField(
        _("Processing status"),
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    processed_at = models.DateTimeField(_("Processed at"), null=True, blank=True)

    class Meta(ConferenceModel.Meta):
        verbose_name = _("Conference webhook receipt")
        verbose_name_plural = _("Conference webhook receipts")

    def __str__(self) -> str:
        """Describe a provider event without retaining its potentially private body."""
        return f"{self.event_type}: {self.event_id}"
