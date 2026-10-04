"""Full non-staff chat through the registered socket, controller and offline runtime."""

from typing import Any
from unittest.mock import patch
from uuid import uuid4

from channels.db import database_sync_to_async
from django.test import override_settings

from bloomerp.agents.controller import AgentController
from bloomerp.models import User
from bloomerp.models.agents import AIAgentAccess, AIConversation, AIRun
from bloomerp.router import router
from bloomerp.tests.agents.test_controller import (
    agent_test_config,
    configure_test_agent,
)
from bloomerp.tests.base import (
    BloomerpChannelTestCase,
    ChannelAction,
    ChannelContext,
    ChannelScenario,
    Connect,
    Disconnect,
    ExpectJson,
)


@override_settings(BLOOMERP_CONFIG=agent_test_config())
class TestAuthenticatedAgentSocket(BloomerpChannelTestCase):
    """Check that an audience grant enables the whole private lifecycle."""

    def setUp(self) -> None:
        """Create a non-staff member and grant use through the new boolean only."""
        super().setUp()
        self.registry = router
        self.creator = User.objects.create_user(username="socket-agent-creator")
        self.user = User.objects.create_user(username="socket-nonstaff")
        self.inactive = User.objects.create_user(
            username="socket-inactive", is_active=False
        )
        self.agent = configure_test_agent(self.creator)
        self.grant = AIAgentAccess.objects.create(
            name="Authenticated audience",
            model=self.agent,
            all_authenticated_users=True,
        )
        self.enterContext(
            patch.object(AgentController, "worker_mode", return_value=False)
        )

    def ready(self, message: dict[str, Any]) -> bool:
        """Recognize the protocol acknowledgement without accepting mere connectivity as success."""
        return message.get("type") == "connection.ready"

    def get_test_scenarios(self) -> list[ChannelScenario]:
        """Declare complete text execution plus anonymous and inactive connection rejection."""
        headers = [(b"host", b"erp.test"), (b"origin", b"https://erp.test")]
        return [
            ChannelScenario(
                name="Authenticated non-staff full chat",
                steps=[
                    Connect(
                        path=f"/ws/agents/{uuid4()}/", user=self.user, headers=headers
                    ),
                    ExpectJson(validators=[self.ready]),
                    ChannelAction(
                        name="Create, execute and read owned conversation",
                        execute=self.full_chat,
                    ),
                    Disconnect(),
                ],
            ),
            ChannelScenario(
                name="Anonymous rejected",
                steps=[
                    Connect(
                        path=f"/ws/agents/{uuid4()}/",
                        headers=headers,
                        accepted=False,
                        close_code=4401,
                    ),
                ],
            ),
            ChannelScenario(
                name="Inactive rejected",
                steps=[
                    Connect(
                        path=f"/ws/agents/{uuid4()}/",
                        user=self.inactive,
                        headers=headers,
                        accepted=False,
                        close_code=4403,
                    ),
                ],
            ),
        ]

    async def full_chat(self, context: ChannelContext) -> None:
        """Wait for real completion, then read history/transcript and test live revocation."""
        socket = context.sockets["default"]
        await socket.send_json_to(
            {
                "type": "chat.message",
                "message": "Hello",
                "agent_id": str(self.agent.pk),
                "client_message_id": str(uuid4()),
            }
        )
        accepted = None
        completed = False
        for _ in range(30):
            event = await socket.receive_json_from(timeout=10)
            if event.get("status") == "accepted":
                accepted = event
            if event.get("event_type") == "run.completed":
                completed = True
            if event.get("event_type") == "run.failed":
                self.fail(f"Offline run failed: {event}")
            if accepted and completed:
                break
        self.assertIsNotNone(accepted)
        self.assertTrue(completed)
        self.conversation_id = accepted["conversation_id"]
        await database_sync_to_async(self.assert_owned_runtime)()
        await socket.send_json_to({"type": "chat.history", "request_id": str(uuid4())})
        history = await socket.receive_json_from(timeout=5)
        self.assertEqual(history["conversations"][0]["id"], self.conversation_id)
        await socket.send_json_to(
            {
                "type": "chat.conversation",
                "request_id": str(uuid4()),
                "conversation_id": self.conversation_id,
            }
        )
        transcript = await socket.receive_json_from(timeout=5)
        self.assertEqual(
            [row["role"] for row in transcript["messages"]], ["user", "assistant"]
        )
        await database_sync_to_async(self.revoke)()
        await socket.send_json_to(
            {
                "type": "chat.message",
                "message": "After revocation",
                "conversation_id": self.conversation_id,
            }
        )
        denied = await socket.receive_json_from(timeout=5)
        self.assertEqual(denied["status"], "forbidden")

    def assert_owned_runtime(self) -> None:
        """Check actor identity and durable provider output after the socket succeeds."""
        conversation = AIConversation.objects.get(pk=self.conversation_id)
        run = AIRun.objects.get(conversation=conversation)
        self.assertEqual(conversation.owner_id, self.user.pk)
        self.assertEqual(conversation.created_by_id, self.user.pk)
        self.assertEqual(run.initiated_by_id, self.user.pk)
        self.assertEqual(run.status, "completed")
        self.assertEqual(
            conversation.messages.get(role="assistant").content_blocks[0]["text"],
            "Hello from the agent.",
        )

    def revoke(self) -> None:
        """Remove use authorization while the original socket remains connected."""
        self.grant.all_authenticated_users = False
        self.grant.save(update_fields=["all_authenticated_users"])
