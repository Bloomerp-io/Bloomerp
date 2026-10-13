"""Declarative lifecycle scenarios for AIToolCall persistence."""

from typing import Any

from django.core.exceptions import ValidationError

from bloomerp.models.agents import AIToolCall
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)

from ._fixtures import AgentModelFixtures


class TestAitoolCallModel(AgentModelFixtures, BloomerpModelTestCase):
    """Exercise immutable arguments and first-dispatch provenance."""

    model = AIToolCall

    def get_test_scenarios(self) -> list[ModelScenario[AIToolCall]]:
        """Declare assignment, reassignment, and cross-run dispatch expectations."""
        return self.with_agent_fixtures(
            [
                ModelScenario(
                    name="First dispatch can be assigned once",
                    create_args=self.proposal_args,
                    update_args=self.first_dispatch_args,
                    update_validators=self.first_dispatch_is_persisted,
                ),
                ModelScenario(
                    name="First dispatch cannot be reassigned",
                    create_args=self.dispatched_args,
                    update_args=self.second_dispatch_args,
                    expected_exceptions=[
                        ExpectedModelException("update", ValidationError, "immutable")
                    ],
                ),
                ModelScenario(
                    name="Tool arguments remain immutable",
                    create_args=self.proposal_args,
                    update_args={"arguments": {"path": "/changed/"}},
                    expected_exceptions=[
                        ExpectedModelException("update", ValidationError, "immutable")
                    ],
                ),
                ModelScenario(
                    name="Dispatch cannot point to a different run",
                    create_args=self.proposal_args,
                    update_args=self.foreign_dispatch_args,
                    expected_exceptions=[
                        ExpectedModelException("update", ValidationError, "this run")
                    ],
                ),
            ]
        )

    def proposal_args(self) -> dict[str, Any]:
        """Prepare a new proposal and its original paused executor."""
        run = self.make_run()
        self.first_attempt = self.make_attempt(run, status="paused")
        return self.tool_args(run)

    def dispatched_args(self) -> dict[str, Any]:
        """Create a proposal whose first executor is already recorded."""
        return self.proposal_args() | self.first_dispatch_args()

    def first_dispatch_args(self) -> dict[str, Any]:
        """Assign the proposal's original execution attempt."""
        return {"first_dispatch_attempt": self.first_attempt}

    def second_dispatch_args(self) -> dict[str, Any]:
        """Attempt to replace original provenance with a later executor."""
        return {
            "first_dispatch_attempt": self.make_attempt(
                self.first_attempt.run, number=2
            )
        }

    def foreign_dispatch_args(self) -> dict[str, Any]:
        """Attach an executor from a different conversation and logical run."""
        other = self.make_run(
            conversation=self.other_conversation,
            trigger_type="event",
            trigger_message=None,
        )
        return {"first_dispatch_attempt": self.make_attempt(other)}

    def first_dispatch_is_persisted(self, tool: AIToolCall) -> bool:
        """Confirm the one-time assignment survives a database read."""
        return tool.first_dispatch_attempt_id == self.first_attempt.pk
