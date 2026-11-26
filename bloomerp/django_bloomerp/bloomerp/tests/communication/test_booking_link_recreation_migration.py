"""Exercise the booking reset against historical records and duplicate metadata."""

from datetime import UTC, datetime, timedelta
from typing import ClassVar

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import StateApps
from django.test import TransactionTestCase

from bloomerp.models.communication.calendar import (
    BookingLink,
    BookingLinkSubmission,
    CalendarEvent,
)


class TestBookingLinkRecreationMigration(TransactionTestCase):
    """Check the replacement tables and retained calendar event relations."""

    previous: ClassVar[list[tuple[str, str]]] = [
        ("bloomerp", "0114_calendar_booking_default_timezone")
    ]
    recreated: ClassVar[list[tuple[str, str]]] = [("bloomerp", "0115_booking_links")]
    current: ClassVar[list[tuple[str, str]]] = [
        ("bloomerp", "0118_booking_link_email_settings")
    ]

    def migrate_to(self, targets: list[tuple[str, str]]) -> StateApps:
        """Apply the requested historical migration state and clear content type lookups."""
        state = MigrationExecutor(connection).migrate(targets)
        ContentType.objects.clear_cache()
        return state.apps

    def test_recreates_booking_records_and_preserves_calendar_events(self) -> None:
        """Reset the old models and retain replacements through the relation rename."""
        self.addCleanup(self.migrate_to, self.current)
        old = self.migrate_to(self.previous)
        user = get_user_model().objects.create_user(username="booking-migration-user")
        for name in (
            "calendarbooking",
            "calendarbookingsubmission",
            "bookinglinksubmission",
        ):
            ContentType.objects.get_or_create(app_label="bloomerp", model=name)
        content_type = ContentType.objects.get_for_model(BookingLink)
        layouts = old.get_model("bloomerp", "UserObjectLayoutPreference").objects
        layout = layouts.create(
            content_type_id=content_type.pk,
            user_id=user.pk,
            name="Booking layout",
            selected=True,
            layout={"rows": []},
        )

        inbox = old.get_model("bloomerp", "Inbox").objects.create(
            user_id=user.pk, name="Booking calendar"
        )
        booking = old.get_model("bloomerp", "CalendarBooking").objects.create(
            title="Existing consultation",
            organizing_inbox=inbox,
            meeting_duration_minutes=30,
        )
        booking.target_inboxes.add(inbox)
        submission = old.get_model(
            "bloomerp", "CalendarBookingSubmission"
        ).objects.create(
            calendar_booking=booking,
            name="Guest",
            email="guest@example.com",
        )
        start = datetime(2026, 11, 25, 10, tzinfo=UTC)
        event = old.get_model("bloomerp", "CalendarEvent").objects.create(
            title="Booked consultation",
            organizer_email="organizer@example.com",
            start=start,
            end=start + timedelta(minutes=30),
            event_timezone="UTC",
            calendar_booking_submission=submission,
        )

        recreated = self.migrate_to(self.recreated)
        Link = recreated.get_model("bloomerp", "BookingLink")
        Submission = recreated.get_model("bloomerp", "BookingLinkSubmission")
        Event = recreated.get_model("bloomerp", "CalendarEvent")
        Field = recreated.get_model("bloomerp", "ApplicationField")

        self.assertFalse(Link.objects.exists())
        self.assertFalse(Submission.objects.exists())
        self.assertEqual(
            ContentType.objects.get_for_model(BookingLink).pk, content_type.pk
        )
        self.assertTrue(
            layouts.filter(pk=layout.pk, content_type_id=content_type.pk).exists()
        )
        retained_event = Event.objects.get(pk=event.pk)
        self.assertEqual(retained_event.start, start)
        self.assertIsNone(retained_event.calendar_booking_submission_id)

        replacement = Link.objects.create(
            organizing_inbox_id=inbox.pk,
            title="New consultation",
            meeting_duration_minutes=30,
        )
        replacement.target_inboxes.add(inbox.pk)
        self.assertEqual(replacement.target_inboxes.get().pk, inbox.pk)
        replacement_submission = Submission.objects.create(
            calendar_booking=replacement,
            name="New guest",
            email="new-guest@example.com",
        )
        retained_event.calendar_booking_submission = replacement_submission
        retained_event.save(update_fields=["calendar_booking_submission"])
        relation = Field.objects.create(
            content_type_id=ContentType.objects.get_for_model(BookingLinkSubmission).pk,
            field="calendar_booking",
            field_type="ForeignKey",
            db_column="calendar_booking_id",
        )

        self.migrate_to(self.current)

        link = BookingLink.objects.get(pk=replacement.pk)
        self.assertTrue(link.auto_approve)
        self.assertEqual(link.location, "")
        self.assertIsNone(link.email_account_id)
        self.assertIsNone(link.email_message)
        saved_submission = BookingLinkSubmission.objects.get(
            pk=replacement_submission.pk
        )
        self.assertEqual(saved_submission.booking_link_id, link.pk)
        self.assertIsNone(saved_submission.requested_start)
        self.assertEqual(saved_submission.calendar_event.pk, event.pk)
        self.assertEqual(CalendarEvent.objects.get(pk=event.pk).start, start)
        relation.refresh_from_db()
        self.assertEqual(relation.field, "booking_link")
        self.assertEqual(relation.db_column, "booking_link_id")
