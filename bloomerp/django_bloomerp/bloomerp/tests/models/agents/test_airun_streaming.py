"""Regress fenced text persistence and its bounded database work."""

from datetime import timedelta
from functools import partial
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models, transaction
from django.db.models.signals import post_save, pre_save
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from bloomerp.agents.runtime import AgentRuntimeTextDeltaEvent
from bloomerp.models.agents import AIApproval, AIMessage, AIRun, AIRunEvent
from bloomerp.tests.base import BloomerpModelTestCase, ModelScenario

from ._fixtures import AgentModelFixtures


class TestAirunStreaming(AgentModelFixtures, BloomerpModelTestCase):
    """Keep streaming cheap without weakening lifecycle and persistence contracts."""

    model = AIRun

    def get_test_scenarios(self) -> list[ModelScenario[AIRun]]:
        """Declare successful text appends and independently rejected mutations."""
        scenarios = [
            ModelScenario(
                name="Subsequent fragments use six reads and retain replay",
                create_operation=self.append_with_query_budget,
            ),
            ModelScenario(
                name="Text writes preserve update stamps and save signals",
                create_operation=self.append_with_stamps,
            ),
            ModelScenario(
                name="Event failure rolls back text and update stamps",
                create_operation=self.reject_event_insert,
            ),
            ModelScenario(
                name="Database still rejects duplicate event sequence",
                create_operation=self.reject_duplicate_sequence,
            ),
            ModelScenario(
                name="Database still rejects missing event foreign key",
                create_operation=self.reject_missing_foreign_key,
            ),
            ModelScenario(
                name="Ordinary saves retain immutable validation",
                create_operation=self.reject_immutable_change,
            ),
            ModelScenario(
                name="Mixed blocks reject missing approval references",
                create_operation=self.reject_foreign_approval,
            ),
            ModelScenario(
                name="Mixed blocks reject foreign approval ownership",
                create_operation=partial(self.reject_foreign_approval, foreign=True),
            ),
            ModelScenario(
                name="Independent text blocks retain their format",
                create_operation=self.append_second_block,
            ),
        ]
        for field in ("run_id", "attempt_id"):
            scenarios.append(
                ModelScenario(
                    name=f"Text event rejects foreign {field}",
                    create_operation=partial(self.reject_event_identity, field=field),
                )
            )
        for condition in ("expired", "wrong_token", "stopped"):
            scenarios.append(
                ModelScenario(
                    name=f"Private text path rejects {condition} lease",
                    create_operation=partial(self.reject_lease, condition=condition),
                )
            )
        for condition in ("role", "status", "run", "conversation"):
            scenarios.append(
                ModelScenario(
                    name=f"Text append rejects wrong message {condition}",
                    create_operation=partial(
                        self.reject_message_identity, condition=condition
                    ),
                )
            )
        for values in (
            {"block_index": -1},
            {"block_index": 2},
            {"block_index": 1, "format": "invalid"},
            {"format": "html"},
        ):
            scenarios.append(
                ModelScenario(
                    name=f"Text append rejects incompatible block {values}",
                    create_operation=partial(self.reject_block, values=values),
                )
            )
        return self.with_agent_fixtures(scenarios)

    def prepare_stream(self) -> AIRun:
        """Create a leased run and persist the first normal text fragment."""
        run = self.make_run()
        self.attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="streaming-test",
            lease_duration=timedelta(minutes=5),
        )
        self.delta = AgentRuntimeTextDeltaEvent(
            run_id=run.pk,
            attempt_id=self.attempt.pk,
            message_id=uuid4(),
            block_index=0,
            text="First",
        )
        run.apply_runtime_event(self.delta, lease_token=self.attempt.lease_token)
        return run

    def snapshot(self, run: AIRun) -> dict[str, Any]:
        """Capture every persisted field touched by or protected from text writes."""
        return {
            "run": AIRun.objects.filter(pk=run.pk).values().get(),
            "message": AIMessage.objects.filter(pk=self.delta.message_id)
            .values()
            .get(),
            "events": list(run.events.values()),
        }

    def append_with_query_budget(self) -> AIRun:
        """Measure real model persistence after initial message/cache setup."""
        run = self.prepare_stream()
        before = self.snapshot(run)
        with CaptureQueriesContext(connection) as queries:
            for text in (" second", " third"):
                run.apply_runtime_event(
                    self.delta.model_copy(update={"text": text}),
                    lease_token=self.attempt.lease_token,
                )
        selects = [
            query
            for query in queries
            if query["sql"].lstrip().upper().startswith("SELECT")
        ]
        self.assertEqual(len(selects), 12)
        self.assertLessEqual(len(queries), 22)
        self.assertFalse(any("bloomerp_label" in query["sql"] for query in queries))
        after = self.snapshot(run)
        self.assertEqual(
            after["message"]["content_blocks"][0]["text"], "First second third"
        )
        for name, value in before["run"].items():
            if name not in {"datetime_updated", "updated_by_id"}:
                self.assertEqual(after["run"][name], value)
        for name, value in before["message"].items():
            if name not in {"content_blocks", "datetime_updated", "updated_by_id"}:
                self.assertEqual(after["message"][name], value)
        replay = [event.public_payload() for event in run.events.all()]
        self.assertEqual([event["sequence"] for event in replay], [1, 2, 3])
        self.assertEqual(
            [event["delta"] for event in replay], ["First", " second", " third"]
        )
        self.assertTrue(
            all(event["message_id"] == str(self.delta.message_id) for event in replay)
        )
        return run

    def append_with_stamps(self) -> AIRun:
        """Verify ordinary save signals, timestamps, and authenticated update stamps."""
        run = self.prepare_stream()
        before = self.snapshot(run)
        instant = timezone.now() + timedelta(seconds=10)
        receivers = []
        for sender in (AIRun, AIMessage, AIRunEvent):
            for signal in (pre_save, post_save):
                receiver = Mock()
                signal.connect(receiver, sender=sender, weak=False)
                receivers.append((signal, sender, receiver))
        try:
            with (
                patch("django.utils.timezone.now", return_value=instant),
                patch(
                    "bloomerp.signals.activity_log_signals.current_request",
                    return_value=SimpleNamespace(user=self.other_user),
                ),
            ):
                stored = run.apply_runtime_event(
                    self.delta.model_copy(update={"text": " stamped"}),
                    lease_token=self.attempt.lease_token,
                )
        finally:
            for signal, sender, receiver in receivers:
                signal.disconnect(receiver, sender=sender)
        after = self.snapshot(run)
        for name in ("run", "message"):
            self.assertEqual(after[name]["datetime_updated"], instant)
            self.assertEqual(after[name]["updated_by_id"], self.other_user.pk)
            self.assertEqual(
                after[name]["created_by_id"], before[name]["created_by_id"]
            )
        self.assertEqual(stored.created_by_id, self.other_user.pk)
        for signal, sender, receiver in receivers:
            receiver.assert_called_once()
            self.assertFalse(receiver.call_args.kwargs.get("raw", False))
        return run

    def reject_event_insert(self) -> AIRun:
        """Roll back both earlier updates if final durable event insertion fails."""
        run = self.prepare_stream()
        before = self.snapshot(run)
        with (
            patch.object(
                AIRunEvent, "_do_insert", side_effect=IntegrityError("insert failed")
            ),
            self.assertRaises(IntegrityError),
        ):
            run.apply_runtime_event(
                self.delta.model_copy(update={"text": " rollback"}),
                lease_token=self.attempt.lease_token,
            )
        self.assertEqual(self.snapshot(run), before)
        return run

    def reject_duplicate_sequence(self) -> AIRun:
        """Confirm event uniqueness still belongs to the database write boundary."""
        run = self.prepare_stream()
        original = run.events.get()
        duplicate = AIRunEvent(
            run=run,
            attempt=self.attempt,
            sequence=original.sequence,
            event_type=original.event_type,
            payload=original.payload,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            models.Model.save(duplicate, force_insert=True)
        return run

    def reject_missing_foreign_key(self) -> AIRun:
        """Exercise actual foreign-key integrity against the complete test schema."""
        run = self.prepare_stream()
        invalid = AIRunEvent(
            run_id=uuid4(), sequence=1, event_type="text.delta", payload={"data": {}}
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            models.Model.save(invalid, force_insert=True)
            connection.check_constraints(table_names=[AIRunEvent._meta.db_table])
        return run

    def reject_immutable_change(self) -> AIRun:
        """Keep generic message/run/event writes behind immutable-field checks."""
        run = self.prepare_stream()
        message = AIMessage.objects.get(pk=self.delta.message_id)
        message.sequence += 1
        with self.assertRaisesMessage(ValidationError, "immutable"):
            message.save()
        run.agent_version = "changed"
        with self.assertRaisesMessage(ValidationError, "immutable"):
            run.save()
        event = run.events.get()
        event.payload["text"] = "changed"
        with self.assertRaisesMessage(ValidationError, "immutable"):
            event.save()
        return AIRun.objects.get(pk=run.pk)

    def reject_event_identity(self, *, field: str) -> AIRun:
        """Reject event identities that do not match the locked leased execution."""
        run = self.prepare_stream()
        before = self.snapshot(run)
        with self.assertRaisesMessage(ValidationError, "another execution"):
            run.apply_runtime_event(
                self.delta.model_copy(update={field: uuid4()}),
                lease_token=self.attempt.lease_token,
            )
        self.assertEqual(self.snapshot(run), before)
        return run

    def reject_lease(self, *, condition: str) -> AIRun:
        """Keep fencing inside the private fast path as well as the public method."""
        run = self.prepare_stream()
        token = self.attempt.lease_token
        if condition == "expired":
            self.attempt.lease_expires_at = timezone.now() - timedelta(seconds=1)
            self.attempt.save()
        elif condition == "wrong_token":
            token = uuid4()
        else:
            run.refresh_from_db()
            run.status = "cancelled"
            run.save()
        before = self.snapshot(run)
        with self.assertRaisesMessage(ValidationError, "lease"):
            run._persist_text_delta(self.delta, lease_token=token)
        self.assertEqual(self.snapshot(run), before)
        return run

    def reject_message_identity(self, *, condition: str) -> AIRun:
        """Do not append into a completed, user-authored, or unrelated message."""
        run = self.prepare_stream()
        args = {
            "conversation": self.conversation,
            "sequence": 3,
            "role": "assistant",
            "status": "streaming",
            "run": run,
        }
        if condition == "role":
            args["role"] = "user"
        elif condition == "status":
            args["status"] = "completed"
        elif condition == "run":
            args["run"] = None
        else:
            args.update(conversation=self.other_conversation, run=None)
        foreign = AIMessage.objects.create(**args)
        before = self.snapshot(run)
        with self.assertRaisesMessage(ValidationError, "message identity"):
            run.apply_runtime_event(
                self.delta.model_copy(update={"message_id": foreign.pk}),
                lease_token=self.attempt.lease_token,
            )
        self.assertEqual(self.snapshot(run), before)
        foreign.refresh_from_db()
        self.assertEqual(foreign.content_blocks, [])
        return run

    def reject_block(self, *, values: dict[str, Any]) -> AIRun:
        """Reject skipped block indexes and a changed format without side effects."""
        run = self.prepare_stream()
        before = self.snapshot(run)
        with self.assertRaises(ValidationError):
            run.apply_runtime_event(
                self.delta.model_copy(update=values),
                lease_token=self.attempt.lease_token,
            )
        self.assertEqual(self.snapshot(run), before)
        return run

    def append_second_block(self) -> AIRun:
        """Allow contiguous new blocks while rejecting text aimed at an artifact."""
        run = self.prepare_stream()
        run.apply_runtime_event(
            self.delta.model_copy(
                update={"block_index": 1, "format": "html", "text": "<b>Next</b>"}
            ),
            lease_token=self.attempt.lease_token,
        )
        message = AIMessage.objects.get(pk=self.delta.message_id)
        self.assertEqual(message.content_blocks[0]["text"], "First")
        self.assertEqual(message.content_blocks[1]["text"], "<b>Next</b>")
        message.content_blocks.append({"type": "artifact", "position": 0})
        message.save()
        before = self.snapshot(run)
        with self.assertRaises(ValidationError):
            run.apply_runtime_event(
                self.delta.model_copy(update={"block_index": 2}),
                lease_token=self.attempt.lease_token,
            )
        self.assertEqual(self.snapshot(run), before)
        return run

    def reject_foreign_approval(self, *, foreign: bool = False) -> AIRun:
        """Retain model clean() checks for approval references in mixed content."""
        run = self.prepare_stream()
        message = AIMessage.objects.get(pk=self.delta.message_id)
        approval_id = uuid4()
        expected = "approval does not exist"
        if foreign:
            other_run = self.make_run(
                conversation=self.other_conversation,
                trigger_message=None,
                trigger_type="schedule",
                initiated_by=self.other_user,
            )
            approval = AIApproval.objects.create(
                **self.approval_args(self.make_tool(other_run))
            )
            approval_id = approval.pk
            expected = "same conversation"
        message.content_blocks.append(
            {"type": "approval", "approval_id": str(approval_id)}
        )
        # Simulate pre-existing invalid provenance; field schema alone accepts it.
        models.Model.save(message, update_fields=["content_blocks"])
        before = self.snapshot(run)
        with self.assertRaisesMessage(ValidationError, expected):
            run.apply_runtime_event(self.delta, lease_token=self.attempt.lease_token)
        self.assertEqual(self.snapshot(run), before)
        return run
