"""Exercise owner-scoped history and transcript snapshot contracts."""

from datetime import timedelta
from uuid import uuid4

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings

from bloomerp.agents.controller import (
    AgentChatRequest,
    AgentController,
    AgentConversationEdit,
    AgentConversationRequest,
    AgentHistoryRequest,
    AgentReplayRequest,
)
from bloomerp.agents.definition import MessageContent
from bloomerp.agents.runtime import AgentRuntimeTextDeltaEvent
from bloomerp.config.definition import BloomerpConfig
from bloomerp.models.agents import AIConversation, AIRun
from bloomerp.tests.agents.test_controller import (
    agent_test_config,
    configure_test_agent,
)


@override_settings(BLOOMERP_CONFIG=agent_test_config())
class AgentHistoryTests(TestCase):
    """Verify controller ownership and transport-ready history independently of a live provider."""

    def setUp(self) -> None:
        """Create two owners and several conversations without exposing other accounts."""
        self.user = get_user_model().objects.create_user(username="history-owner")
        self.other = get_user_model().objects.create_user(username="history-other")
        self.ai_agent = configure_test_agent(self.user)
        self.controller = AgentController(self.user)
        self.first = AIConversation.objects.create(
            owner=self.user, title="First conversation"
        )
        self.second = AIConversation.objects.create(
            owner=self.user, title="Second conversation"
        )
        self.foreign = AIConversation.objects.create(
            owner=self.other, title="Private foreign title"
        )

    def test_owner_search_archive_and_keyset_pagination(self) -> None:
        """Page owned conversations, search titles and separate archives from the active list."""
        request = AgentHistoryRequest(request_id=uuid4(), limit=1)
        page = self.controller.conversation_history(request)
        self.assertEqual(page["conversations"][0]["id"], str(self.second.pk))
        next_page = self.controller.conversation_history(
            request.model_copy(update={"cursor": page["cursor"]})
        )
        self.assertEqual(next_page["conversations"][0]["id"], str(self.first.pk))
        self.assertIsNone(next_page["cursor"])
        self.assertNotIn("Private foreign", str(page) + str(next_page))
        self.controller.edit_conversation(
            AgentConversationEdit(
                request_id=uuid4(),
                conversation_id=self.first.pk,
                title="Renamed",
                archived=True,
            )
        )
        archived = self.controller.conversation_history(
            AgentHistoryRequest(request_id=uuid4(), archived=True, search="name")
        )
        self.assertEqual(
            [row["title"] for row in archived["conversations"]], ["Renamed"]
        )
        self.controller.edit_conversation(
            AgentConversationEdit(
                request_id=uuid4(), conversation_id=self.first.pk, archived=False
            )
        )
        self.assertEqual(
            len(
                self.controller.conversation_history(
                    AgentHistoryRequest(request_id=uuid4())
                )["conversations"]
            ),
            2,
        )

    def test_foreign_read_rename_archive_and_cursor_are_rejected(self) -> None:
        """Deny cross-owner history access regardless of guessed identifiers."""
        with self.assertRaises(PermissionDenied):
            self.controller.conversation_detail(
                AgentConversationRequest(
                    request_id=uuid4(), conversation_id=self.foreign.pk
                )
            )
        with self.assertRaises(PermissionDenied):
            self.controller.edit_conversation(
                AgentConversationEdit(
                    request_id=uuid4(),
                    conversation_id=self.foreign.pk,
                    title="Stolen",
                    archived=True,
                )
            )
        with self.assertRaises(ValidationError):
            self.controller.conversation_history(
                AgentHistoryRequest(request_id=uuid4(), cursor="invalid")
            )
        with self.assertRaises(ValidationError):
            self.controller.edit_conversation(
                AgentConversationEdit(
                    request_id=uuid4(), conversation_id=self.first.pk, title="   "
                )
            )

    def test_history_works_without_provider_configuration(self) -> None:
        """Saved history stays available when credentials or provider setup are absent."""
        with override_settings(BLOOMERP_CONFIG=BloomerpConfig(bloomai_settings=None)):
            self.assertEqual(
                len(
                    self.controller.conversation_history(
                        AgentHistoryRequest(request_id=uuid4())
                    )["conversations"]
                ),
                2,
            )

    def test_snapshot_boundary_and_older_messages(self) -> None:
        """Load persisted text once and replay only text committed after the snapshot."""
        for index in range(4):
            self.first.append_message(
                role="user",
                message_id=uuid4(),
                content=MessageContent(root=[{"type": "text", "text": str(index)}]),
            )
        submission = self.controller.accept_message(
            AgentChatRequest(
                conversation_id=self.first.pk,
                content=[{"type": "text", "text": "Continue"}],
            )
        )
        run = AIRun.objects.get(pk=submission.run_id)
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="test",
            lease_duration=timedelta(minutes=1),
        )
        message_id = uuid4()
        event = AgentRuntimeTextDeltaEvent(
            run_id=run.pk,
            attempt_id=attempt.pk,
            message_id=message_id,
            block_index=0,
            text="Hello",
            format="markdown",
        )
        first_event = run.apply_runtime_event(event, lease_token=attempt.lease_token)
        request = AgentConversationRequest(
            request_id=uuid4(), conversation_id=self.first.pk, limit=2
        )
        snapshot = self.controller.conversation_detail(request)
        self.assertEqual(snapshot["messages"][-1]["content"][0]["text"], "Hello")
        self.assertEqual(snapshot["run"]["cursor"], first_event.sequence)
        older = self.controller.conversation_detail(
            request.model_copy(update={"before_sequence": snapshot["before_sequence"]})
        )
        self.assertLess(
            older["messages"][-1]["sequence"], snapshot["messages"][0]["sequence"]
        )
        run.apply_runtime_event(
            event.model_copy(update={"text": " world"}), lease_token=attempt.lease_token
        )
        replay = self.controller.replay_page(
            AgentReplayRequest(
                conversation_id=self.first.pk,
                run_id=run.pk,
                after_sequence=snapshot["run"]["cursor"],
            )
        )
        self.assertEqual([item.payload.text for item in replay.events], [" world"])
        self.assertNotIn("checkpoint", str(snapshot))

    def test_archive_preserves_run_and_blocks_new_messages(self) -> None:
        """Archiving affects discovery and new input, never cancellation or persisted work."""
        submission = self.controller.accept_message(
            AgentChatRequest(
                conversation_id=self.first.pk,
                content=[{"type": "text", "text": "Continue"}],
            )
        )
        self.controller.edit_conversation(
            AgentConversationEdit(
                request_id=uuid4(), conversation_id=self.first.pk, archived=True
            )
        )
        run = AIRun.objects.get(pk=submission.run_id)
        self.assertEqual(run.status, "queued")
        self.assertIsNone(run.cancel_requested_at)
        snapshot = self.controller.conversation_detail(
            AgentConversationRequest(request_id=uuid4(), conversation_id=self.first.pk)
        )
        self.assertEqual(snapshot["run"]["status"], "queued")
        async_to_sync(self.controller.cancel)(run.pk)
        count = self.first.messages.count()
        with self.assertRaises(ValidationError):
            self.controller.accept_message(
                AgentChatRequest(
                    conversation_id=self.first.pk,
                    content=[{"type": "text", "text": "No"}],
                )
            )
        self.assertEqual(self.first.messages.count(), count)

    def test_owner_can_change_approval_rules_and_other_owners_cannot(self) -> None:
        """Persist conversation policy changes without changing another conversation's defaults."""
        rules = {"default": "never", "tools": {"fixture_effect": "always"}}
        response = self.controller.edit_conversation(
            AgentConversationEdit(
                request_id=uuid4(),
                conversation_id=self.first.pk,
                approval_rules=rules,
            )
        )
        self.first.refresh_from_db()
        self.assertEqual(self.first.approval_rules, rules)
        self.assertEqual(response["conversation"]["approval_rules"], rules)
        snapshot = self.controller.conversation_detail(
            AgentConversationRequest(
                request_id=uuid4(),
                conversation_id=self.first.pk,
            )
        )
        self.assertEqual(snapshot["conversation"]["approval_rules"], rules)
        self.second.refresh_from_db()
        self.assertEqual(self.second.approval_rules, {})
        with self.assertRaises(PermissionDenied):
            AgentController(self.other).edit_conversation(
                AgentConversationEdit(
                    request_id=uuid4(),
                    conversation_id=self.first.pk,
                    approval_rules={"default": "always"},
                )
            )
        self.first.refresh_from_db()
        self.assertEqual(self.first.approval_rules, rules)

    def test_initial_approval_rules_are_owned_by_conversation_and_snapshot(
        self,
    ) -> None:
        """Create a new chat with selected rules and retain them independently of the AI agent."""
        submission = self.controller.accept_message(
            AgentChatRequest(
                content=[{"type": "text", "text": "No approval needed"}],
                approval_rules={"default": "never"},
            )
        )
        conversation = AIConversation.objects.get(pk=submission.conversation_id)
        self.assertEqual(conversation.approval_rules["default"], "never")
        self.assertEqual(
            conversation.runs.get().config_snapshot["approval_rules"]["default"],
            "never",
        )
        self.assertNotIn(
            "approval_rules", {field.name for field in self.ai_agent._meta.fields}
        )
