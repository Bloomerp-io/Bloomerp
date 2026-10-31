"""Append-only observations and acceptance evidence for native signing."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .base import SigningModel
from .definition import validate_json_object
from .signature_recipient import SignatureRecipient


class SignatureEvent(SigningModel):
    """Record a request event without granting it the status of qualified signing."""

    class EventType(models.TextChoices):
        """Enumerate evidence produced by the native signing lifecycle."""

        CREATED = "created", _("Created")
        SENT = "sent", _("Sent")
        VIEWED = "viewed", _("Viewed")
        CONSENTED = "consented", _("Consented")
        FIELD_COMPLETED = "field_completed", _("Field completed")
        SIGNED = "signed", _("Signed")
        DECLINED = "declined", _("Declined")
        CANCELLED = "cancelled", _("Cancelled")
        EXPIRED = "expired", _("Expired")
        COMPLETED = "completed", _("Completed")

    request_bound = True
    append_only = True
    request = models.ForeignKey(
        "bloomerp.SignatureRequest",
        on_delete=models.PROTECT,
        related_name="events",
        verbose_name=_("Request"),
    )
    recipient = models.ForeignKey(
        "bloomerp.SignatureRecipient",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="events",
        verbose_name=_("Recipient"),
    )
    event_type = models.CharField(
        _("Event type"), max_length=24, choices=EventType.choices
    )
    occurred_at = models.DateTimeField(_("Occurred at"), default=timezone.now)
    ip_address = models.GenericIPAddressField(_("IP address"), null=True, blank=True)
    user_agent = models.TextField(_("User agent"), blank=True)
    payload = models.JSONField(
        _("Payload"), default=dict, blank=True, validators=[validate_json_object]
    )

    class Meta(SigningModel.Meta):
        verbose_name = _("Signature event")
        verbose_name_plural = _("Signature events")
        ordering = ("occurred_at", "pk")

    def clean(self) -> None:
        """Require recipient evidence to refer to a member of the same request."""
        super().clean()
        if (
            self.recipient_id
            and not SignatureRecipient.objects.using(self._state.db)
            .filter(pk=self.recipient_id, request_id=self.request_id)
            .exists()
        ):
            raise ValidationError(
                {"recipient": _("The recipient must belong to this request.")}
            )
        try:
            validate_json_object(self.payload)
        except ValidationError as error:
            raise ValidationError({"payload": error.messages}) from error

    def __str__(self) -> str:
        """Describe an event without exposing its potentially personal payload."""
        return f"{self.event_type}: {self.request_id}"
