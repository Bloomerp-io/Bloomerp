"""Declarative lifecycle scenarios for AIMessage persistence."""

from typing import Any
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest
from django.test import override_settings

from bloomerp.agents.artifacts.file import FILE_ARTIFACT, FileArtifactPayload
from bloomerp.agents.artifacts.selection import selection_item
from bloomerp.agents.controller import AgentChatRequest, AgentController
from bloomerp.models import File
from bloomerp.models.agents import AIMessage
from bloomerp.tests.agents.test_controller import agent_test_config
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)

from ._fixtures import AgentModelFixtures


class TestAimessageModel(AgentModelFixtures, BloomerpModelTestCase):
    """Exercise transcript ordering, payload validation, and guarded ORM writes."""

    model = AIMessage

    def get_test_scenarios(self) -> list[ModelScenario[AIMessage]]:
        """Declare successful transcript writes and explicit invalid operations."""
        return self.with_agent_fixtures(
            [
                ModelScenario(
                    name="Attachments are persisted once on submission retries",
                    create_operation=self.submit_attachment,
                    create_validators=self.attachment_persisted,
                ),
                ModelScenario(
                    name="Another user cannot reuse a signed selection",
                    create_operation=self.foreign_selection,
                    expected_exceptions=[
                        ExpectedModelException("create", PermissionDenied)
                    ],
                ),
                ModelScenario(
                    name="Revoked file permission blocks submission",
                    create_operation=self.revoked_selection,
                    expected_exceptions=[
                        ExpectedModelException("create", PermissionDenied)
                    ],
                ),
                ModelScenario(
                    name="Modified tokens are rejected",
                    create_operation=self.forged_selection,
                    expected_exceptions=[
                        ExpectedModelException("create", PermissionDenied)
                    ],
                ),
                ModelScenario(
                    name="Append a message in sequence",
                    create_args=self.message_args,
                    create_validators=self.sequence_is_preserved,
                ),
                ModelScenario(
                    name="Duplicate message sequence is rejected",
                    create_args=self.duplicate_args,
                    expected_exceptions=[
                        ExpectedModelException("create", ValidationError)
                    ],
                ),
                ModelScenario(
                    name="Message cannot reference another conversation's run",
                    create_args=self.foreign_run_args,
                    expected_exceptions=[
                        ExpectedModelException(
                            "create", ValidationError, "conversation"
                        )
                    ],
                ),
                ModelScenario(
                    name="Unknown message blocks are rejected on update",
                    create_args=self.message_args,
                    update_args={
                        "content_blocks": [{"type": "script", "text": "unexpected"}]
                    },
                    expected_exceptions=[
                        ExpectedModelException(
                            "update", ValidationError, "content_blocks"
                        )
                    ],
                ),
                ModelScenario(
                    name="QuerySet update cannot bypass validation",
                    create_operation=self.queryset_update,
                    expected_exceptions=[
                        ExpectedModelException("create", TypeError, "QuerySet.update")
                    ],
                ),
                ModelScenario(
                    name="Bulk create cannot bypass validation",
                    create_operation=self.bulk_create,
                    expected_exceptions=[
                        ExpectedModelException("create", TypeError, "bulk_create")
                    ],
                ),
                ModelScenario(
                    name="Bulk update cannot bypass validation",
                    create_operation=self.bulk_update,
                    expected_exceptions=[
                        ExpectedModelException("create", TypeError, "bulk_update")
                    ],
                ),
            ]
        )

    def message_args(self) -> dict[str, Any]:
        """Append a plain assistant message after the fixture's user message."""
        return {"conversation": self.conversation, "sequence": 2, "role": "assistant"}

    def duplicate_args(self) -> dict[str, Any]:
        """Reuse the first transcript position in the same conversation."""
        return self.message_args() | {"sequence": 1}

    def foreign_run_args(self) -> dict[str, Any]:
        """Attach another conversation's response to the existing run."""
        return self.message_args() | {
            "conversation": self.other_conversation,
            "run": self.make_run(),
        }

    def sequence_is_preserved(self, message: AIMessage) -> bool:
        """Verify ordering and role survive the framework's database refresh."""
        return message.sequence == 2 and message.role == "assistant"

    def queryset_update(self) -> AIMessage:
        """Attempt a prohibited bulk mutation on an existing transcript entry."""
        AIMessage.objects.filter(pk=self.message.pk).update(content_blocks=[])
        return self.message

    def bulk_create(self) -> AIMessage:
        """Attempt the prohibited bulk-create path even for an empty batch."""
        AIMessage.objects.bulk_create([])
        return self.message

    def bulk_update(self) -> AIMessage:
        """Attempt a prohibited bulk update of an existing message."""
        AIMessage.objects.bulk_update([self.message], ["role"])
        return self.message

    def file_token(self) -> str:
        """Create an authorized source and signed selection for the fixture owner."""
        self.user.is_superuser = True
        self.user.save()
        source = File.objects.create(
            name="invoice.pdf", file="test/invoice.pdf", persisted=True
        )
        request = HttpRequest()
        request.user = self.user
        return selection_item(
            FILE_ARTIFACT,
            FileArtifactPayload(
                file_id=source.pk, name=source.name, media_type="application/pdf"
            ),
            request,
        )["token"]

    @override_settings(BLOOMERP_CONFIG=agent_test_config())
    def submit_attachment(self) -> AIMessage:
        """Retry an attachment-only submission through the production controller."""
        token = self.file_token()
        request = AgentChatRequest(
            content=[{"type": "text", "text": ""}],
            attachments=[token],
            client_message_id=uuid4(),
        )
        controller = AgentController(self.user)
        first = controller.accept_message(request)
        second = controller.accept_message(request)
        self.assertEqual(first, second)
        self.assertEqual(len(first.artifact_ids), 1)
        return AIMessage.objects.get(pk=first.message_id)

    def attachment_persisted(self, message: AIMessage) -> bool:
        """Check ordered links, source identity and transcript restoration metadata."""
        link = message.artifact_links.get()
        snapshot = message.conversation.transcript_page()
        return (
            link.artifact.file_id is not None
            and link.artifact.created_by_message_id == message.pk
            and message.content_blocks[-1] == {"type": "artifact", "position": 0}
            and snapshot["messages"][0]["artifacts"][0]["id"] == str(link.artifact_id)
            and message.triggered_runs.count() == 1
        )

    @override_settings(BLOOMERP_CONFIG=agent_test_config())
    def foreign_selection(self) -> AIMessage:
        """Reject another user's signed candidate before any chat rows are created."""
        AgentController(self.other_user).accept_message(
            AgentChatRequest(
                content=[{"type": "text", "text": "Inspect"}],
                attachments=[self.file_token()],
            )
        )
        return self.message

    @override_settings(BLOOMERP_CONFIG=agent_test_config())
    def revoked_selection(self) -> AIMessage:
        """Recheck current access rather than trusting earlier search authorization."""
        token = self.file_token()
        self.user.is_superuser = False
        self.user.save()
        AgentController(self.user).accept_message(
            AgentChatRequest(
                content=[{"type": "text", "text": "Inspect"}], attachments=[token]
            )
        )
        return self.message

    @override_settings(BLOOMERP_CONFIG=agent_test_config())
    def forged_selection(self) -> AIMessage:
        """Reject candidate metadata altered after signing."""
        AgentController(self.user).accept_message(
            AgentChatRequest(
                content=[{"type": "text", "text": "Inspect"}],
                attachments=[self.file_token() + "tampered"],
            )
        )
        return self.message
