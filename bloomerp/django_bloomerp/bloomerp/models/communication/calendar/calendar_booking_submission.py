"""Visitor booking details retained independently of the resulting shared event."""

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .base import CalendarModel


class CalendarBookingSubmission(CalendarModel):
    """Record booking origin without duplicating the event's scheduled time."""

    calendar_booking = models.ForeignKey(
        "bloomerp.CalendarBooking",
        on_delete=models.PROTECT,
        related_name="submissions",
        verbose_name=_("Calendar booking"),
    )
    name = models.CharField(_("Name"), max_length=255)
    email = models.EmailField(_("Email"))
    submitted_at = models.DateTimeField(_("Submitted at"), default=timezone.now)

    class Meta(CalendarModel.Meta):
        verbose_name = _("Calendar booking submission")
        verbose_name_plural = _("Calendar booking submissions")

    def __str__(self) -> str:
        """Identify a submission by its visitor and email address."""
        return f"{self.name} <{self.email}>"
