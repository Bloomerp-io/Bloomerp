"""Verify the consolidated calendar schema and recognition of previously applied development migrations."""

from datetime import UTC, datetime, timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class CalendarSchedulingMigrationTests(TransactionTestCase):
    """Inspect the actual migration graph and final historical schema."""

    def test_final_calendar_schema_contains_only_current_models(self) -> None:
        """Create distinct event identities without any retired delivery bookkeeping."""
        loader = MigrationExecutor(connection).loader
        state = loader.project_state([("bloomerp", "0099_calendar")])
        event_model = state.apps.get_model("bloomerp", "CalendarEvent")
        with self.assertRaises(LookupError):
            state.apps.get_model("bloomerp", "CalendarSchedulingDelivery")
        self.assertTrue(
            {
                "last_sent_fingerprint",
                "pending_send_fingerprint",
                "pending_send_method",
            }.isdisjoint(field.name for field in event_model._meta.get_fields())
        )
        stamp = datetime(2026, 10, 15, 12, tzinfo=UTC)
        events = [
            event_model.objects.create(
                title=f"Migrated event {number}",
                organizer_email="organizer@example.com",
                start=stamp,
                end=stamp + timedelta(hours=1),
                event_timezone="UTC",
            )
            for number in range(2)
        ]
        self.assertNotEqual(events[0].calendar_uid, events[1].calendar_uid)
        self.assertIsNotNone(
            state.apps.get_model("bloomerp", "CalendarSchedulingCancellation")
        )

    def test_applied_calendar_history_is_recognized_by_replacement(self) -> None:
        """Avoid replaying schema operations on databases that applied the former migration chain."""
        executor = MigrationExecutor(connection)
        target = ("bloomerp", "0099_calendar")
        migration = executor.loader.disk_migrations[target]
        self.assertEqual(
            migration.dependencies, [("bloomerp", "0098_merge_20261016_1033")]
        )
        self.assertEqual(len(migration.replaces), 7)
        self.assertEqual(executor.migration_plan([target]), [])
        self.assertEqual(executor.loader.graph.leaf_nodes("bloomerp"), [target])
