"""Declarative lifecycle scenarios for AIConversation persistence."""

import json
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from bloomerp.agents.definition import MessageContent
from bloomerp.agents.memory import MAX_CONTEXT_CHARS, remember_tool_result
from bloomerp.models.agents import (
    AIArtifact,
    AIConversation,
    AIMessage,
    AIMessageArtifact,
    AIRun,
    AIToolCall,
)
from bloomerp.services.sql_services import DatabaseTable, Field
from bloomerp.tests.base import BloomerpModelTestCase, ModelScenario
from bloomerp.views.api.sql.memory import CONTEXT_PREFIX

from ._fixtures import AgentModelFixtures


class TestAiconversationModel(AgentModelFixtures, BloomerpModelTestCase):
    """Exercise aggregate deletion despite internal restricted provenance links."""

    model = AIConversation

    def get_test_scenarios(self) -> list[ModelScenario[AIConversation]]:
        """Declare conversation creation, related graph setup, and cascade deletion."""
        return self.with_agent_fixtures(
            [
                ModelScenario(
                    name="Discovery carries across requests without replaying tool history",
                    create_args=self.conversation_args,
                    post_create=self.prepare_discovery,
                    create_validators=self.discovery_is_carried,
                ),
                ModelScenario(
                    name="Discovery respects current access and bounded context",
                    create_args=self.conversation_args,
                    post_create=self.prepare_discovery,
                    create_validators=self.discovery_is_filtered,
                ),
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

    def prepare_discovery(self, conversation: AIConversation) -> None:
        """Store partial discovery, unrelated calls, and subsequent request boundaries."""
        first = conversation.append_message(
            role="user",
            message_id=uuid4(),
            content=MessageContent.model_validate(
                [{"type": "text", "text": "Count staff"}]
            ),
        )
        run = self.make_run(
            conversation=conversation, trigger_message=first, status="completed"
        )
        self.store_discovery(run, "employee", ["id", "department", "revoked"])
        self.store_discovery(run, "employee", ["id"])
        self.store_discovery(run, "removed_table", ["id"])
        self.store_discovery(run, "failed_table", ["id"], status="failed")
        self.store_discovery(run, "wrong_tool", ["id"], tool="another_tool")
        foreign_message = self.other_conversation.append_message(
            role="user",
            message_id=uuid4(),
            content=MessageContent.model_validate(
                [{"type": "text", "text": "Other chat"}]
            ),
        )
        foreign = self.make_run(
            conversation=self.other_conversation,
            trigger_message=foreign_message,
            initiated_by=self.other_user,
            status="completed",
        )
        self.store_discovery(foreign, "foreign_table", ["id"])
        second = conversation.append_message(
            role="user",
            message_id=uuid4(),
            content=MessageContent.model_validate(
                [{"type": "text", "text": "Update staff"}]
            ),
        )
        second_run = self.make_run(
            conversation=conversation, trigger_message=second, status="completed"
        )
        self.second_discovery_run = second_run
        conversation.append_message(
            role="user",
            message_id=uuid4(),
            content=MessageContent.model_validate(
                [{"type": "text", "text": "Pivot staff"}]
            ),
        )

    def store_discovery(
        self,
        run: AIRun,
        table: str,
        fields: list[str],
        *,
        status: str = "completed",
        tool: str = "api_sql_accessible_tables",
    ) -> None:
        """Persist realistic structured discovery with deliberately stale type metadata."""
        saved = self.make_tool(
            run,
            provider_call_id=str(uuid4()),
            tool_identifier=tool,
            status=status,
            result={
                "structuredContent": {
                    "databases": [
                        {
                            "name": "bloomerp",
                            "tables": [
                                {
                                    "name": table,
                                    "model_label": "old.Employee",
                                    "fields": [
                                        {"name": name, "field_type": "OldType"}
                                        for name in fields
                                    ],
                                }
                            ],
                        }
                    ]
                }
            },
        )

        remember_tool_result(saved)
        remember_tool_result(saved)  # Replaying a completed tool must be idempotent.

    def accessible_discovery_tables(self) -> list[DatabaseTable]:
        """Describe current visibility, including tables that must not leak into memory."""
        return [
            DatabaseTable(
                name="employee",
                model_label="bloomerp_modules.Employee",
                fields=[
                    Field(name=name, field_type="UUIDField")
                    for name in ["id", "department", "location"]
                ],
            ),
            *[
                DatabaseTable(
                    name=name, fields=[Field(name="id", field_type="UUIDField")]
                )
                for name in ["foreign_table", "failed_table", "wrong_tool"]
            ],
        ]

    def discovery_is_carried(self, conversation: AIConversation) -> bool:
        """Verify deduplication, run boundaries, canonical labels and resume behavior."""
        with patch(
            "bloomerp.services.sql_services.SqlExecutor.get_accessible_tables_and_fields",
            return_value=self.accessible_discovery_tables(),
        ) as accessible:
            first = conversation.messages_to_runtime_messages(through_sequence=1)
            self.assertEqual([message.role for message in first], ["user"])
            accessible.assert_not_called()
            second = conversation.messages_to_runtime_messages(through_sequence=2)
            self.store_discovery(self.second_discovery_run, "employee", ["location"])
            third = conversation.messages_to_runtime_messages(through_sequence=3)
            for history, fields in [
                (second, {"id", "department"}),
                (third, {"id", "department", "location"}),
            ]:
                self.assertEqual(history[0].role, "system")
                text = history[0].content[0].text
                self.assertLessEqual(len(text), MAX_CONTEXT_CHARS)
                entries = json.loads(text.removeprefix(CONTEXT_PREFIX))
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0]["model_label"], "bloomerp_modules.Employee")
                self.assertEqual(set(entries[0]["fields"]), fields)
                self.assertNotIn("OldType", text)
            accessible.reset_mock()
            resumed = conversation.messages_to_runtime_messages(after_sequence=2)
            self.assertEqual([message.sequence for message in resumed], [3])
            accessible.assert_not_called()
        return True

    def discovery_is_filtered(self, conversation: AIConversation) -> bool:
        """Remove revoked schema and omit oversized entries without truncating JSON."""
        with patch(
            "bloomerp.services.sql_services.SqlExecutor.get_accessible_tables_and_fields",
            return_value=[],
        ):
            self.assertTrue(
                all(
                    message.role == "user"
                    for message in conversation.messages_to_runtime_messages()
                )
            )
        with (
            patch(
                "bloomerp.services.sql_services.SqlExecutor.get_accessible_tables_and_fields",
                return_value=self.accessible_discovery_tables(),
            ),
            patch(
                "bloomerp.agents.memory.MAX_CONTEXT_CHARS",
                len(CONTEXT_PREFIX) + 2,
            ),
        ):
            self.assertTrue(
                all(
                    message.role == "user"
                    for message in conversation.messages_to_runtime_messages()
                )
            )
        return True

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
