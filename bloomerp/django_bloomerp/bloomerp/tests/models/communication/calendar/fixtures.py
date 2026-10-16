"""Small model graphs for declarative calendar persistence scenarios."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model

from bloomerp.models.communication.calendar import (
    CalendarBooking,
    CalendarBookingSubmission,
)
from bloomerp.models.communication.inbox.inbox import Inbox


class CalendarFixtures:
    """Build explicit placements without assuming any inbox owner is an attendee."""

    def prepare(self) -> None:
        """Create independent inboxes, booking configuration, and submission origin."""
        self.user = get_user_model().objects.create_user(username="calendar-user")
        self.inbox = Inbox.objects.create(user=self.user, name="Personal calendar")
        self.team_inbox = Inbox.objects.create(user=self.user, name="Team calendar")
        self.booking = CalendarBooking.objects.create(**self.booking_args())
        self.submission = CalendarBookingSubmission.objects.create(
            **self.submission_args()
        )

    def event_args(self, **overrides: Any) -> dict[str, Any]:
        """Build an aware Brussels meeting without duplicating its UTC instant."""
        start = datetime(2026, 10, 15, 14, tzinfo=ZoneInfo("Europe/Brussels"))
        return {
            "title": "Planning",
            "organizer_email": "organizer@example.com",
            "start": start,
            "end": start + timedelta(hours=1),
            "event_timezone": "Europe/Brussels",
            **overrides,
        }

    def booking_args(self, **overrides: Any) -> dict[str, Any]:
        """Build a draft booking configuration with an explicit sending inbox."""
        return {
            "title": "Customer meeting",
            "organizing_inbox": self.inbox,
            "meeting_duration_minutes": 30,
            "timezone": "Europe/Brussels",
            "description": "Discuss your project",
            **overrides,
        }

    def submission_args(self, **overrides: Any) -> dict[str, Any]:
        """Build visitor details independently of the resulting event's time."""
        return {
            "calendar_booking": self.booking,
            "name": "Visitor",
            "email": "visitor@example.com",
            **overrides,
        }
