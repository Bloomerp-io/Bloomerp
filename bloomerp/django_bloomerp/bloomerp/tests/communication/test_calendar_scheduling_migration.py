"""Validate scheduling metadata migration against multiple existing meeting records."""

from datetime import UTC, datetime, timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class CalendarSchedulingMigrationTests(TransactionTestCase):
    """Exercise historical model state without applying migrations to the project database."""

    def test_existing_events_receive_distinct_stable_calendar_uids(self) -> None:
        """Backfill unique UIDs before enforcing organizer-scoped scheduling identity."""
        old_target = [("bloomerp", "0098_calendar_models")]
        new_target = [("bloomerp", "0099_calendar_scheduling")]
        executor = MigrationExecutor(connection)
        restore_targets = executor.loader.graph.leaf_nodes("bloomerp")
        executor.migrate(old_target)
        try:
            old_apps = executor.loader.project_state(old_target).apps
            event_model = old_apps.get_model("bloomerp", "CalendarEvent")
            start = datetime(2026, 10, 15, 12, tzinfo=UTC)
            event_ids = [
                event_model.objects.create(
                    title=f"Existing meeting {number}",
                    organizer_email="organizer@example.com",
                    start=start,
                    end=start + timedelta(hours=1),
                    event_timezone="UTC",
                ).pk
                for number in range(2)
            ]
            executor = MigrationExecutor(connection)
            executor.migrate(new_target)
            new_apps = executor.loader.project_state(new_target).apps
            migrated = new_apps.get_model("bloomerp", "CalendarEvent")
            uids = list(
                migrated.objects.filter(pk__in=event_ids).values_list(
                    "calendar_uid", flat=True
                )
            )
            self.assertEqual(len(set(uids)), 2)
            self.assertEqual(set(uids), {f"{pk}@bloomerp" for pk in event_ids})
        finally:
            MigrationExecutor(connection).migrate(restore_targets)

    def test_delivery_removal_preserves_calendar_protocol_state(self) -> None:
        """Drop delivery bookkeeping while retaining meetings, RSVP history, and tombstones."""
        old_target = [("bloomerp", "0099_calendar_scheduling")]
        new_target = [("bloomerp", "0100_remove_calendar_scheduling_delivery")]
        executor = MigrationExecutor(connection)
        restore_targets = executor.loader.graph.leaf_nodes("bloomerp")
        executor.migrate(old_target)
        try:
            old_apps = executor.loader.project_state(old_target).apps
            stamp = datetime(2026, 10, 15, 12, tzinfo=UTC)
            event = old_apps.get_model("bloomerp", "CalendarEvent").objects.create(
                title="Scheduled meeting",
                calendar_uid="retained@test",
                organizer_email="organizer@example.com",
                start=stamp,
                end=stamp + timedelta(hours=1),
                event_timezone="UTC",
                sequence=4,
                scheduling_dtstamp=stamp,
                invitation_sent_at=stamp,
                last_sent_fingerprint="obsolete",
                pending_send_fingerprint="obsolete-pending",
                pending_send_method="REQUEST",
            )
            attendee = old_apps.get_model(
                "bloomerp", "CalendarEventParticipant"
            ).objects.create(
                event=event,
                email="attendee@example.com",
                response_status="accepted",
                last_sent_reply_sequence=4,
                last_sent_reply_status="accepted",
            )
            cancellation = old_apps.get_model(
                "bloomerp", "CalendarSchedulingCancellation"
            ).objects.create(
                calendar_uid="cancelled@test",
                organizer_email="organizer@example.com",
                sequence=3,
                dtstamp=stamp,
            )
            account = old_apps.get_model("bloomerp", "EmailAccount").objects.create(
                name="Calendar sender",
                email_address="organizer@example.com",
                provider="imap_smtp",
            )
            delivery_model = old_apps.get_model(
                "bloomerp", "CalendarSchedulingDelivery"
            )
            delivery_table = delivery_model._meta.db_table
            delivery_model.objects.create(
                event=event,
                email_account=account,
                recipient="attendee@example.com",
                method="REQUEST",
                sequence=4,
                fingerprint="obsolete",
                payload=b"obsolete calendar mail",
                status="sent",
            )
            executor = MigrationExecutor(connection)
            executor.migrate(new_target)
            new_apps = executor.loader.project_state(new_target).apps
            with self.assertRaises(LookupError):
                new_apps.get_model("bloomerp", "CalendarSchedulingDelivery")
            self.assertNotIn(delivery_table, connection.introspection.table_names())
            event_model = new_apps.get_model("bloomerp", "CalendarEvent")
            self.assertTrue(
                {
                    "last_sent_fingerprint",
                    "pending_send_fingerprint",
                    "pending_send_method",
                }.isdisjoint(field.name for field in event_model._meta.get_fields())
            )
            retained = event_model.objects.get(pk=event.pk)
            self.assertEqual(retained.calendar_uid, "retained@test")
            self.assertEqual(retained.sequence, 4)
            self.assertEqual(retained.invitation_sent_at, stamp)
            retained_attendee = new_apps.get_model(
                "bloomerp", "CalendarEventParticipant"
            ).objects.get(pk=attendee.pk)
            self.assertEqual(retained_attendee.last_sent_reply_sequence, 4)
            self.assertEqual(retained_attendee.last_sent_reply_status, "accepted")
            self.assertTrue(
                new_apps.get_model("bloomerp", "CalendarSchedulingCancellation")
                .objects.filter(pk=cancellation.pk, sequence=3)
                .exists()
            )
        finally:
            MigrationExecutor(connection).migrate(restore_targets)
