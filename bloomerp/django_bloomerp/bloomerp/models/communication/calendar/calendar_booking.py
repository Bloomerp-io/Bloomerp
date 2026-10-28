"""Reusable public booking configuration, separate from visitor submissions."""

import uuid
from typing import ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop

from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models.definition import (
    BloomerpModelConfig,
    DetailViewSettings,
    FieldLayout,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
)

from .base import CalendarModel
from .validators import validate_calendar_timezone


class CalendarBooking(CalendarModel):
    """Configure a booking offering without inferring attendees from inboxes."""

    bloomerp_config = BloomerpModelConfig(
        module="communication",
        model_view_settings=ModelViewSettings(
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("Calendar bookings"),
                    display_fields=[
                        "title",
                        "organizing_inbox",
                        "meeting_duration_minutes",
                        "timezone",
                        "active",
                    ],
                    sort_field="title",
                )
            ]
        ),
        detail_view_settings=DetailViewSettings(
            layouts=[
                FieldLayout(
                    rows=[
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Booking"),
                            items=[
                                LayoutItem(id="title"),
                                LayoutItem(id="active"),
                                LayoutItem(id="description", colspan=2),
                            ],
                        ),
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Availability"),
                            items=[
                                LayoutItem(id="meeting_duration_minutes"),
                                LayoutItem(id="timezone"),
                                LayoutItem(id="availability_hours", colspan=2),
                            ],
                        ),
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Inboxes"),
                            items=[
                                LayoutItem(id="organizing_inbox"),
                                LayoutItem(id="target_inboxes"),
                            ],
                        ),
                    ]
                )
            ]
        ),
    )

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
