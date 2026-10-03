"""Declarative lifecycle scenarios for AIConversation persistence."""

from typing import Any
from uuid import uuid4

from bloomerp.agents.definition import MessageContent
from bloomerp.models.agents import (
    AIArtifact,
    AIConversation,
    AIMessage,
    AIMessageArtifact,
    AIRun,
    AIToolCall,
)
from bloomerp.tests.base import BloomerpModelTestCase, ModelScenario

from ._fixtures import AgentModelFixtures


class TestAiconversationModel(AgentModelFixtures, BloomerpModelTestCase):
    """Exercise aggregate deletion despite internal restricted provenance links."""

    model = AIConversation

    def get_test_scenarios(self) -> list[ModelScenario[AIConversation]]:
        """Declare conversation creation, related graph setup, and cascade deletion."""
        return self.with_agent_fixtures(
            [
                ModelScenario(
                    name="Rename archive and restore retain the transcript",
                    create_args=self.conversation_args,
                    post_create=self.append_history,
                    create_validators=self.metadata_preserves_history,
                ),
                ModelScenario(
                    name="Message append deduplicates and excludes interrupted history",
                    create_args=self.conversation_args,
                    post_create=self.append_history,
                    create_validators=self.history_is_complete_and_ordered,
                ),
                ModelScenario(
                    name="Delete complete conversation with internal references",
                    create_args=self.conversation_args,
                    post_create=self.populate_conversation,
                    create_validators=self.graph_is_present,
                    delete_validators=self.graph_is_deleted,
                ),
            ]
        )

    def conversation_args(self) -> dict[str, Any]:
        """Create the aggregate that the scenario framework will later delete."""
        return {"owner": self.user}

    def populate_conversation(self, conversation: AIConversation) -> None:
        """Populate the aggregate with run, tool, attachment, and revision links."""
        self.aggregate_message = AIMessage.objects.create(
            conversation=conversation,
            sequence=1,
            role="user",
            content_blocks=[{"type": "text", "text": "Analyze"}],
        )
        self.aggregate_run = self.make_run(
            conversation=conversation, trigger_message=self.aggregate_message
        )
        self.aggregate_tool = self.make_tool(self.aggregate_run)
        self.aggregate_artifact = self.make_chart(
            conversation=conversation,
            created_by_tool_call=self.aggregate_tool,
            created_by_message=self.aggregate_message,
        )
        self.aggregate_attachment = AIMessageArtifact.objects.create(
            message=self.aggregate_message,
            artifact=self.aggregate_artifact,
            position=0,
        )
        self.aggregate_revision = self.make_chart(
            conversation=conversation, previous_revision=self.aggregate_artifact
        )

    def graph_is_present(self, conversation: AIConversation) -> bool:
        """Verify the related aggregate exists before testing its deletion."""
        return (
            conversation.number_of_messages == 1
            and self.aggregate_run.conversation_id == conversation.pk
        )

    def graph_is_deleted(self, conversation: AIConversation) -> bool:
        """Check every child disappears along with the deleted aggregate root."""
        records = (
            (AIConversation, conversation.pk),
            (AIMessage, self.aggregate_message.pk),
            (AIRun, self.aggregate_run.pk),
            (AIToolCall, self.aggregate_tool.pk),
            (AIArtifact, self.aggregate_artifact.pk),
            (AIArtifact, self.aggregate_revision.pk),
            (AIMessageArtifact, self.aggregate_attachment.pk),
        )
        return all(not model.objects.filter(pk=pk).exists() for model, pk in records)

    def append_history(self, conversation: AIConversation) -> None:
        """Append the same user submission twice and an interrupted assistant response."""
        message_id = uuid4()
        content = MessageContent.model_validate([{"type": "text", "text": "Hello"}])
        for _ in range(2):
            conversation.append_message(
                content=content, role="user", message_id=message_id
            )
        conversation.append_message(
            content=content, role="assistant", message_id=uuid4(), status="interrupted"
        )

    def history_is_complete_and_ordered(self, conversation: AIConversation) -> bool:
        """Confirm duplicate identities allocate no new sequence and partial output stays out."""
        history = conversation.messages_to_runtime_messages()
        return (
            conversation.number_of_messages == 2
            and len(history) == 1
            and history[0].sequence == 1
        )

    def metadata_preserves_history(self, conversation: AIConversation) -> bool:
        """Exercise model-local metadata methods without deleting or rewriting messages."""
        original = list(conversation.messages.values_list("pk", flat=True))
        conversation.edit_metadata(title=" Renamed ", archived=True)
        archived = conversation.status == "archived" and conversation.title == "Renamed"
        conversation.edit_metadata(archived=False)
        return (
            archived
            and conversation.status == "open"
            and original == list(conversation.messages.values_list("pk", flat=True))
        )
