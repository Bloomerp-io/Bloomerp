"""Shared Inbox placement fixtures for generated calendar request scenarios."""

from datetime import datetime, time, timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone

from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.services.preference_services import PreferenceManager


class InboxCalendarFixtures:
    """Build placements that differ deliberately from organizer and attendee identity."""

    def prepare_calendar(self) -> None:
        """Create a selected shared reference with timed, all-day, and unrelated meetings."""
        self.actor = get_user_model().objects.create_superuser(
            username="inbox-calendar-reader", password=None
        )
        self.owner = get_user_model().objects.create_user(
            username="inbox-calendar-owner", is_staff=True
        )
        self.outsider = get_user_model().objects.create_user(
            username="inbox-calendar-outsider", is_staff=True
        )
        self.source = Inbox.objects.create(
            user=self.owner, name="Shared calendar inbox"
        )
        self.other_inbox = Inbox.objects.create(
            user=self.owner, name="Other calendar inbox"
        )
        self.source.shared_with_users.add(self.actor)
        PreferenceManager(self.actor).select(self.source)
        self.reference = Inbox.objects.get(user=self.actor, source_object=self.source)
        self.today = timezone.localdate()
        self.start = timezone.make_aware(datetime.combine(self.today, time(10)))
        self.timed = self.create_event("Placed timed meeting")
        self.timed.inboxes.add(self.source, self.other_inbox)
        self.all_day = self.create_event(
            "Placed all-day meeting",
            all_day=True,
            start=None,
            end=None,
            event_timezone=None,
            start_date=self.today,
            end_date=self.today + timedelta(days=2),
        )
        self.all_day.inboxes.add(self.source)
        self.cancelled = self.create_event("Cancelled meeting", cancelled=True)
        self.cancelled.inboxes.add(self.source)
        self.unplaced = self.create_event(
            "Unrelated organizer and attendee meeting", organizing_inbox=self.source
        )
        self.unplaced.inboxes.add(self.other_inbox)
        self.unplaced.participants.create(user=self.actor)

    def create_event(self, title: str, **overrides: Any) -> CalendarEvent:
        """Create a valid timed meeting unless the caller supplies date-only values."""
        return CalendarEvent.objects.create(
            **{
                "title": title,
                "organizer_email": "organizer@example.com",
                "start": self.start,
                "end": self.start + timedelta(hours=1),
                "event_timezone": "UTC",
                **overrides,
            }
        )
