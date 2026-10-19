"""Attendance identities and independent responses to shared calendar events."""

from typing import Any, ClassVar

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from .base import CalendarModel


class CalendarEventParticipant(CalendarModel):
    """Identify an internal user or external email without implying placement."""

    class ResponseStatus(models.TextChoices):
        AWAITING_RESPONSE = "awaiting_response", _("Awaiting response")
        ACCEPTED = "accepted", _("Accepted")
        TENTATIVE = "tentative", _("Tentative")
        DECLINED = "declined", _("Declined")

    event = models.ForeignKey(
        "bloomerp.CalendarEvent",
        on_delete=models.CASCADE,
        related_name="participants",
        verbose_name=_("Event"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="calendar_participations",
        verbose_name=_("User"),
    )
    email = models.EmailField(_("Invited email"), blank=True)
    display_name = models.CharField(_("Display name"), max_length=255, blank=True)
    response_status = models.CharField(
        _("Response status"),
        max_length=24,
        choices=ResponseStatus.choices,
        default=ResponseStatus.AWAITING_RESPONSE,
    )
    reply_sequence = models.PositiveIntegerField(null=True, blank=True, editable=False)
    reply_dtstamp = models.DateTimeField(null=True, blank=True, editable=False)
    last_sent_reply_sequence = models.PositiveIntegerField(
        null=True, blank=True, editable=False
    )
    last_sent_reply_status = models.CharField(max_length=24, blank=True, editable=False)
    invitation_cancelled = models.BooleanField(default=False, editable=False)
    responded_at = models.DateTimeField(_("Responded at"), null=True, blank=True)

    class Meta(CalendarModel.Meta):
        verbose_name = _("Calendar event participant")
        verbose_name_plural = _("Calendar event participants")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(user__isnull=False) | ~models.Q(email=""),
                name="calendar_participant_has_identity",
            ),
            models.UniqueConstraint(
                fields=["event", "user"],
                condition=models.Q(user__isnull=False),
                name="calendar_participant_event_user_unique",
            ),
            models.UniqueConstraint(
                models.F("event"),
                Lower("email"),
                condition=~models.Q(email=""),
                name="calendar_participant_event_email_unique",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Normalize invited email whitespace before identity validation."""
        self.email = self.email.strip()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Label a participant using their name, invited email, or user identity."""
        return self.display_name or self.email or str(self.user)
