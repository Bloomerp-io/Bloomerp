"""Browser-bound requests to enter a shared meeting, separate from chat membership."""

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import ConferenceModel


class ConferenceAdmission(ConferenceModel):
    """Require a host decision before a link visitor receives media credentials."""

    class Status(models.TextChoices):
        WAITING = "waiting", _("Waiting")
        ADMITTED = "admitted", _("Admitted")
        REJECTED = "rejected", _("Not admitted")

    immutable_fields = ("session_id", "browser_key", "user_id", "display_name")
    session = models.ForeignKey(
        "bloomerp.ConferenceSession",
        on_delete=models.CASCADE,
        related_name="admissions",
    )
    browser_key = models.UUIDField(default=uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    display_name = models.CharField(_("Name"), max_length=255)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.WAITING
    )
    participant = models.ForeignKey(
        "bloomerp.ConferenceParticipant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="admissions",
    )

    class Meta(ConferenceModel.Meta):
        verbose_name = _("Meeting admission")
        verbose_name_plural = _("Meeting admissions")

    def clean(self) -> None:
        """Keep admission decisions attached to a participant in the same session."""
        super().clean()
        if (self.status == self.Status.ADMITTED) != bool(self.participant_id):
            raise ValidationError("Only admitted requests must have a participant.")
        if self.participant_id and (
            self.participant.session_id != self.session_id
            or self.participant.user_id != self.user_id
        ):
            raise ValidationError(
                "Admission identity must match its session and account."
            )

    def validate_previous(self, previous: "ConferenceAdmission") -> None:
        """Keep a host decision final and prevent changing its admitted identity."""
        super().validate_previous(previous)
        if previous.status != self.Status.WAITING and (
            previous.status != self.status
            or previous.participant_id != self.participant_id
        ):
            raise ValidationError("This admission has already been decided.")

    def __str__(self) -> str:
        """Display the account-derived or guest-supplied waiting-room name."""
        return self.display_name
