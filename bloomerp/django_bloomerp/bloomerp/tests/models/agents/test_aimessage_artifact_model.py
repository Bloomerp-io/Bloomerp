"""Declarative lifecycle scenarios for message artifact links."""

from typing import Any

from django.core.exceptions import ValidationError

from bloomerp.models.agents import AIMessageArtifact
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)

from ._fixtures import AgentModelFixtures


class TestAimessageArtifactModel(AgentModelFixtures, BloomerpModelTestCase):
    """Exercise attachment positioning and conversation ownership."""

    model = AIMessageArtifact

    def get_test_scenarios(self) -> list[ModelScenario[AIMessageArtifact]]:
        """Declare successful attachment and foreign-conversation rejection."""
        return self.with_agent_fixtures(
            [
                ModelScenario(
                    name="Attach artifact within its conversation",
                    create_args=self.attachment_args,
                    create_validators=self.attachment_is_persisted,
                ),
                ModelScenario(
                    name="Attachment cannot cross conversations",
                    create_args=self.foreign_attachment_args,
                    expected_exceptions=[
                        ExpectedModelException(
                            "create", ValidationError, "conversation"
                        )
                    ],
                ),
            ]
        )

    def attachment_args(self) -> dict[str, Any]:
        """Link a chart to its conversation's first transcript message."""
        return {"message": self.message, "artifact": self.make_chart(), "position": 0}

    def foreign_attachment_args(self) -> dict[str, Any]:
        """Link a different conversation's chart to the current message."""
        return {
            "message": self.message,
            "artifact": self.make_chart(conversation=self.other_conversation),
            "position": 0,
        }

    def attachment_is_persisted(self, attachment: AIMessageArtifact) -> bool:
        """Verify attachment position and ownership after persistence."""
        return (
            attachment.position == 0
            and attachment.message.conversation_id
            == attachment.artifact.conversation_id
        )
