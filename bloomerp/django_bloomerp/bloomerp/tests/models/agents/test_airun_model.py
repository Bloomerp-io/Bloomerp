"""Declarative lifecycle scenarios for AIRun persistence."""

from datetime import timedelta
from functools import partial
from typing import Any
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models
from django.utils import timezone

from bloomerp.agents.definition import AgentConfigSnapshot, RunUsage
from bloomerp.agents.runtime import (
    AgentRuntimeTextDeltaEvent,
    AgentRuntimeUsageUpdatedEvent,
)
from bloomerp.models.agents import AIRun
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)

from ._fixtures import AgentModelFixtures


class TestAirunModel(AgentModelFixtures, BloomerpModelTestCase):
    """Exercise run payloads, provenance, concurrency, and immutable configuration."""

    model = AIRun

    def get_test_scenarios(self) -> list[ModelScenario[AIRun]]:
        """Declare independent create and update outcomes for durable runs."""
        scenarios = [
            ModelScenario(
                name="Usage snapshots replace rather than accumulate within an attempt",
                create_operation=self.create_with_usage_snapshots,
                create_validators=self.usage_is_not_double_counted,
            ),
            ModelScenario(
                name="Expired leases cannot append text",
                create_operation=self.append_with_expired_lease,
                expected_exceptions=[
                    ExpectedModelException("create", ValidationError, "lease")
                ],
            ),
            ModelScenario(
                name="Typed configuration round-trips as JSON",
                create_args=partial(
                    self.run_args,
                    config_snapshot=AgentConfigSnapshot(
                        runtime="test", provider="test", model="test"
                    ),
                ),
                create_validators=[
                    self.configuration_is_json,
                    self.budget_schema_is_preserved,
                ],
            ),
            ModelScenario(
                name="Scheduled run needs no synthetic message",
                create_args=partial(
                    self.run_args, trigger_message=None, trigger_type="schedule"
                ),
                create_validators=self.trigger_is_absent,
            ),
            ModelScenario(
                name="Message-triggered run requires provenance",
                create_args=partial(self.run_args, trigger_message=None),
                expected_exceptions=[
                    ExpectedModelException("create", ValidationError, "trigger_message")
                ],
            ),
            ModelScenario(
                name="Trigger cannot cross conversations",
                create_args=self.foreign_trigger_args,
                expected_exceptions=[
                    ExpectedModelException("create", ValidationError, "conversation")
                ],
            ),
            ModelScenario(
                name="Waiting run retains the conversation slot",
                create_operation=self.create_conflicting_run,
                expected_exceptions=[
                    ExpectedModelException(
                        "create", ValidationError, "ai_one_unfinished_run"
                    )
                ],
            ),
            ModelScenario(
                name="Database arbitrates conflicting inserts",
                create_operation=self.insert_conflicting_run,
                expected_exceptions=[ExpectedModelException("create", IntegrityError)],
            ),
            ModelScenario(
                name="Completed run releases the conversation slot",
                create_args=partial(
                    self.run_args, status="waiting", wait_condition={"kind": "approval"}
                ),
                update_args=self.completed_args,
                update_validators=self.conversation_slot_is_released,
            ),
            ModelScenario(
                name="Configuration remains immutable",
                create_args=self.run_args,
                update_args={
                    "config_snapshot": {
                        "runtime": "test",
                        "provider": "test",
                        "model": "changed",
                    }
                },
                expected_exceptions=[
                    ExpectedModelException("update", ValidationError, "immutable")
                ],
            ),
            ModelScenario(
                name="Database field rejects invalid budgets",
                create_operation=self.insert_invalid_budget,
                expected_exceptions=[
                    ExpectedModelException("create", ValidationError, "max_tokens")
                ],
            ),
            ModelScenario(
                name="Database field rejects non-JSON checkpoint data",
                create_operation=self.insert_non_json_checkpoint,
                expected_exceptions=[ExpectedModelException("create", ValidationError)],
            ),
        ]
        for name, values in (
            ("Required config fields cannot be omitted", {"config_snapshot": {}}),
            ("Token budgets cannot be negative", {"budgets": {"max_tokens": -1}}),
            (
                "Browser context cannot supply an actor",
                {"origin_browser_context": {"user_id": "forged"}},
            ),
            (
                "Configuration cannot persist API credentials",
                {
                    "config_snapshot": {
                        "runtime": "x",
                        "provider": "x",
                        "model": "x",
                        "api_key": "secret",
                    }
                },
            ),
        ):
            scenarios.append(
                ModelScenario(
                    name=name,
                    create_args=partial(self.run_args, **values),
                    expected_exceptions=[
                        ExpectedModelException("create", ValidationError)
                    ],
                )
            )
        return self.with_agent_fixtures(scenarios)

    def configuration_is_json(self, run: AIRun) -> bool:
        """Check typed inputs persist as primitives and retain transcript context."""
        return (
            isinstance(run.config_snapshot, dict)
            and run.config_snapshot["runtime"] == "test"
            and run.conversation.number_of_messages == 1
        )

    def budget_schema_is_preserved(self, run: AIRun) -> bool:
        """Keep the field schema identifier available for migration serialization."""
        return run._meta.get_field("budgets").deconstruct()[3]["schema"] == "budgets.v1"

    def trigger_is_absent(self, run: AIRun) -> bool:
        """Confirm the schedule trigger persists without a message foreign key."""
        return run.trigger_message_id is None

    def foreign_trigger_args(self) -> dict[str, Any]:
        """Point a run at a conversation different from its triggering message."""
        return self.run_args(conversation=self.other_conversation)

    def create_conflicting_run(self) -> AIRun:
        """Attempt a second run while an approval wait occupies the conversation."""
        self.make_run(status="waiting", wait_condition={"kind": "approval"})
        return self.make_run()

    def insert_conflicting_run(self) -> AIRun:
        """Bypass model validation to exercise database concurrency arbitration."""
        self.make_run()
        duplicate = AIRun(**self.run_args())
        models.Model.save(duplicate)
        return duplicate

    def completed_args(self) -> dict[str, Any]:
        """Supply a terminal status and timestamp for the framework update phase."""
        return {"status": "completed", "finished_at": timezone.now()}

    def conversation_slot_is_released(self, run: AIRun) -> bool:
        """Verify a new queued run can be persisted after the first completes."""
        return self.make_run().pk != run.pk

    def insert_invalid_budget(self) -> AIRun:
        """Exercise field write validation without invoking AgentModel.clean."""
        run = AIRun(**self.run_args(budgets={"max_tokens": -1}))
        models.Model.save(run)
        return run

    def insert_non_json_checkpoint(self) -> AIRun:
        """Exercise JSON normalization directly at the database write boundary."""
        run = AIRun(**self.run_args(checkpoint={"not_json": object()}))
        models.Model.save(run)
        return run

    def create_with_usage_snapshots(self) -> AIRun:
        """Apply successive cumulative attempt totals through the model event boundary."""
        run = self.make_run()
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="test",
            lease_duration=timedelta(seconds=60),
        )
        for tokens in (3, 7):
            run.apply_runtime_event(
                AgentRuntimeUsageUpdatedEvent(
                    run_id=run.pk,
                    attempt_id=attempt.pk,
                    usage=RunUsage(output_tokens=tokens),
                ),
                lease_token=attempt.lease_token,
            )
        run.refresh_from_db()
        return run

    def usage_is_not_double_counted(self, run: AIRun) -> bool:
        """Verify the persisted attempt and run contain the latest total exactly once."""
        return (
            run.usage["output_tokens"] == 7
            and run.attempts.get().usage["output_tokens"] == 7
        )

    def append_with_expired_lease(self) -> AIRun:
        """Attempt to emit text after another executor could legally take ownership."""
        run = self.make_run()
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="dead",
            lease_duration=timedelta(seconds=60),
        )
        attempt.lease_expires_at = timezone.now() - timedelta(seconds=1)
        attempt.save()
        run.apply_runtime_event(
            AgentRuntimeTextDeltaEvent(
                run_id=run.pk,
                attempt_id=attempt.pk,
                message_id=uuid4(),
                block_index=0,
                text="Stale",
            ),
            lease_token=attempt.lease_token,
        )
        return run
