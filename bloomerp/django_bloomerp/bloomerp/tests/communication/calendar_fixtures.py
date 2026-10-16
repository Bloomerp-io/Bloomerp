"""Scheduling fixtures shared by email integration and generated component tests."""

from datetime import UTC, date, datetime, timedelta

from django.contrib.auth import get_user_model
from icalendar import Calendar, Event, vCalAddress

from bloomerp.communication.builtins.emails.actions import (
    _upsert_email_inbox_item_result,
)
from bloomerp.communication.builtins.emails.base_adapter import (
    BloomerpEmail,
    CalendarEmailPart,
)
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem

STAMP = datetime(2026, 1, 1, tzinfo=UTC)
UID = "meeting@example.com"


class SchedulingFixtures:
    """Create actual connected email folders without inferring attendee identities."""

    def prepare_calendar(self) -> None:
        """Create permitted actor, unprivileged owner, account, and two calendar inboxes."""
        self.actor = get_user_model().objects.create_superuser(
            username="calendar-scheduler", email="scheduler@example.com", password=None
        )
        self.owner = get_user_model().objects.create_user(
            username="calendar-owner", email="owner@example.com"
        )
        self.outsider = get_user_model().objects.create_user(
            username="calendar-outsider"
        )
        self.inbox = Inbox.objects.create(user=self.owner, name="Scheduling inbox")
        self.team = Inbox.objects.create(user=self.owner, name="Shared sales inbox")
        self.account = EmailAccount.objects.create(
            email_address="owner@example.com",
            status="active",
            sync_enabled=True,
            mailboxes=["INBOX"],
        )
        self.folder = InboxFolder.objects.create(
            inbox=self.inbox, type="email", related_object_id=str(self.account.pk)
        )
        self.second_folder = InboxFolder.objects.create(
            inbox=self.team, type="email", related_object_id=str(self.account.pk)
        )
        self.inbox.shared_with_users.add(self.actor)
        self.team.shared_with_users.add(self.actor)

    def make_email(
        self,
        method: str = "REQUEST",
        *,
        sequence: int = 0,
        seconds: int = 0,
        attendees: tuple[str, ...] = ("owner@example.com", "other@example.com"),
        sender: str | None = None,
        organizer: str = "organizer@example.com",
        status: str = "ACCEPTED",
        all_day: bool = False,
        recurring: bool = False,
    ) -> BloomerpEmail:
        """Build genuine iTIP payloads for reorder, identity, and timezone tests."""
        calendar = Calendar()
        calendar.add("PRODID", "-//Calendar integration tests//EN")
        calendar.add("VERSION", "2.0")
        calendar.add("METHOD", method)
        event = Event()
        event.add("UID", UID)
        event.add("ORGANIZER", vCalAddress(f"mailto:{organizer}"))
        event.add("SEQUENCE", sequence)
        event.add("DTSTAMP", STAMP + timedelta(seconds=seconds))
        if method == "REQUEST":
            event.add("SUMMARY", f"Planning revision {sequence}")
            event.add(
                "DTSTART",
                date(2026, 10, 15)
                if all_day
                else datetime(2026, 10, 15, 12 + sequence, tzinfo=UTC),
            )
            event.add(
                "DTEND",
                date(2026, 10, 17)
                if all_day
                else datetime(2026, 10, 15, 13 + sequence, tzinfo=UTC),
            )
        if recurring:
            event.add("RRULE", {"FREQ": "DAILY"})
        for address in attendees:
            attendee = vCalAddress(f"mailto:{address}")
            attendee.params["PARTSTAT"] = (
                status if method == "REPLY" else "NEEDS-ACTION"
            )
            event.add("ATTENDEE", attendee)
        calendar.add_component(event)
        payload = calendar.to_ical().decode()
        return BloomerpEmail(
            provider="imap",
            provider_message_id=f"{method}-{sequence}-{seconds}",
            email_account_id=str(self.account.pk),
            subject="Meeting",
            sender=sender or (attendees[0] if method == "REPLY" else organizer),
            to=[self.account.email_address],
            message_id=f"<{method}-{sequence}-{seconds}@test>",
            calendar_parts=[CalendarEmailPart(content=payload, method=method)],
        )

    def index_email(
        self, email: BloomerpEmail, folder: InboxFolder | None = None
    ) -> InboxItem:
        """Exercise the real email persistence and scheduling integration boundary."""
        return _upsert_email_inbox_item_result(email, folder or self.folder)[0]

    def local_event(self) -> CalendarEvent:
        """Create a local organizer's meeting with two explicitly invited recipients."""
        event = CalendarEvent.objects.create(
            calendar_uid=UID,
            organizer_email=self.account.email_address,
            organizing_inbox=self.inbox,
            title="Local planning",
            start=datetime(2026, 10, 15, 12, tzinfo=UTC),
            end=datetime(2026, 10, 15, 13, tzinfo=UTC),
            event_timezone="UTC",
        )
        event.inboxes.add(self.inbox, self.team)
        event.participants.create(email="first@example.com")
        event.participants.create(email="second@example.com")
        return event
