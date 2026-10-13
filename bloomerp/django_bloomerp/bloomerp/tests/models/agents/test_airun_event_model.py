"""Declarative lifecycle scenarios for AIRunEvent persistence."""

from typing import Any

from django.core.exceptions import ValidationError

from bloomerp.models.agents import AIRunEvent
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)

from ._fixtures import AgentModelFixtures


class TestAirunEventModel(AgentModelFixtures, BloomerpModelTestCase):
    """Exercise ordered immutable events and same-run provenance."""

    model = AIRunEvent

    def get_test_scenarios(self) -> list[ModelScenario[AIRunEvent]]:
        """Declare persisted event payloads and independent invalid references."""
        return self.with_agent_fixtures(
            [
                ModelScenario(
                    name="Event text persists and remains immutable",
                    create_args=self.event_args,
                    create_validators=self.text_is_preserved,
                    update_args={"payload": {"text": "changed"}},
                    expected_exceptions=[
                        ExpectedModelException("update", ValidationError, "immutable")
                    ],
                ),
                ModelScenario(
                    name="Duplicate event sequence is rejected",
                    create_args=self.duplicate_args,
                    expected_exceptions=[
                        ExpectedModelException("create", ValidationError)
                    ],
                ),
                ModelScenario(
                    name="Event cannot reference a foreign artifact",
                    create_args=self.foreign_artifact_args,
                    expected_exceptions=[
                        ExpectedModelException("create", ValidationError, "artifact_id")
                    ],
                ),
                ModelScenario(
                    name="Event attempt must belong to its run",
                    create_args=self.foreign_attempt_args,
                    expected_exceptions=[
                        ExpectedModelException("create", ValidationError, "this run")
                    ],
                ),
            ]
        )

    def event_args(self) -> dict[str, Any]:
        """Create the first text event for a fresh logical run."""
        return {
            "run": self.make_run(),
            "sequence": 1,
            "event_type": "text.delta",
            "payload": {"text": "hello"},
        }

    def duplicate_args(self) -> dict[str, Any]:
        """Propose a second event using an existing position in the same run."""
        values = self.event_args()
        AIRunEvent.objects.create(**values)
        return values | {"event_type": "run.completed", "payload": {}}

    def foreign_artifact_args(self) -> dict[str, Any]:
        """Reference an artifact outside the event's conversation."""
        artifact = self.make_chart(conversation=self.other_conversation)
        return self.event_args() | {
            "event_type": "artifact.created",
            "payload": {"artifact_id": str(artifact.pk)},
        }

    def foreign_attempt_args(self) -> dict[str, Any]:
        """Reference an executor belonging to an unrelated logical run."""
        other = self.make_run(
            conversation=self.other_conversation,
            trigger_type="event",
            trigger_message=None,
        )
        return self.event_args() | {"attempt": self.make_attempt(other)}

    def text_is_preserved(self, event: AIRunEvent) -> bool:
        """Verify replay position and payload after the framework refreshes the row."""
        return event.sequence == 1 and event.payload["text"] == "hello"
