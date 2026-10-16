"""Reusable public booking configuration, separate from visitor submissions."""

import uuid
from typing import ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import CalendarModel
from .validators import validate_calendar_timezone


class CalendarBooking(CalendarModel):
    """Configure a booking offering without inferring attendees from inboxes."""

    organizing_inbox = models.ForeignKey(
        "bloomerp.Inbox",
        on_delete=models.PROTECT,
        related_name="organized_calendar_bookings",
        verbose_name=_("Organizing inbox"),
    )
    target_inboxes = models.ManyToManyField(
        "bloomerp.Inbox",
        related_name="calendar_bookings",
        blank=True,
        verbose_name=_("Destination inboxes"),
    )
    title = models.CharField(_("Title"), max_length=255)
    description = models.TextField(_("Description"), blank=True)
    meeting_duration_minutes = models.PositiveIntegerField(
        _("Meeting duration in minutes"),
        validators=[MinValueValidator(1)],
    )
    availability_hours = models.JSONField(
        _("Availability hours"), default=dict, blank=True
    )
    timezone = models.CharField(
        _("Availability timezone"),
        max_length=255,
        validators=[validate_calendar_timezone],
    )
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    active = models.BooleanField(_("Active"), default=False)

    class Meta(CalendarModel.Meta):
        verbose_name = _("Calendar booking")
        verbose_name_plural = _("Calendar bookings")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(meeting_duration_minutes__gt=0),
                name="calendar_booking_positive_duration",
            ),
        ]

    def __str__(self) -> str:
        """Return the offering's title independently of its destination inboxes."""
        return self.title
