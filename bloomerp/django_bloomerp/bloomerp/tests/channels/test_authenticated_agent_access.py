"""Full non-staff chat through the registered socket, controller and offline runtime."""

from typing import Any
from unittest.mock import patch
from uuid import uuid4

from channels.db import database_sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

from bloomerp.agents.controller import AgentController
from bloomerp.filters.definition import FilterCondition
from bloomerp.models import FileNode, User
from bloomerp.models.agents import AIAgentAccess, AIConversation, AIRun
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.project_management.todo import Todo
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
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
        self.foreign = AIConversation.objects.create(
            owner=self.creator, selected_agent=self.agent
        )
        self.todo = Todo.objects.create(
            title="Referenced task",
            content="Context from the workspace",
            priority="urgent",
        )
        content_type = ContentType.objects.get_for_model(Todo)
        for field_name in ("title", "content", "priority"):
            ApplicationField.objects.get_or_create(
                content_type=content_type,
                field=field_name,
                defaults={"field_type": "CharField"},
            )
        self.todo_policy = PolicyManager.create_policy(
            Todo,
            global_permissions=["view"],
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view"],
                    conditions=[
                        FilterCondition(
                            field_path="title",
                            lookup_id="equals",
                            value=self.todo.title,
                        )
                    ],
                )
            ],
            field_permissions={"content": "view"},
        )
        self.todo_policy.assign_user(self.user)
        self.todo_reference = {
            "kind": "object",
            "target_id": str(self.todo.pk),
            "content_type_id": content_type.pk,
        }
        self.image = FileNode.objects.create(
            name="editor-image.png",
            content="editor-image.png",
            kind="FILE",
            created_by=self.user,
        )
        self.enterContext(
            patch.object(AgentController, "worker_mode", return_value=False)
        )

    def ready(self, message: dict[str, Any]) -> bool:
        """Recognize the protocol acknowledgement without accepting mere connectivity as success."""
        return message.get("type") == "connection.ready"

    def get_test_scenarios(self) -> list[ChannelScenario]:
        """Declare Markdown execution plus anonymous and inactive connection rejection."""
        headers = [(b"host", b"erp.test"), (b"origin", b"https://erp.test")]
        return [
            ChannelScenario(
                name="Authenticated non-staff sends Markdown and reads the reply",
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
        """Execute an owned Markdown prompt and check transcript access and live revocation."""
        socket = context.sockets["default"]
        await socket.send_json_to(
            {
                "type": "chat.message",
                "message": "**Hello**",
                "format": "markdown",
                "attachments": [
                    self.todo_reference,
                    {"kind": "file", "target_id": str(self.image.pk)},
                ],
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
            if event.get("status") in {"failed", "forbidden", "unavailable"}:
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
        self.assertEqual(
            transcript["messages"][0]["content"],
            [
                {"type": "text", "format": "markdown", "text": "**Hello**"},
                {"type": "artifact", "position": 0},
                {"type": "artifact", "position": 1},
            ],
        )
        self.assertEqual(len(transcript["messages"][0]["artifacts"]), 2)
        for action in ("chat.conversation", "chat.message"):
            payload = {
                "type": action,
                "conversation_id": str(self.foreign.pk),
            }
            if action == "chat.message":
                payload["message"] = "Foreign conversation"
            else:
                payload["request_id"] = str(uuid4())
            await socket.send_json_to(payload)
            denied = await socket.receive_json_from(timeout=5)
            self.assertEqual(denied["status"], "forbidden")
        for field, value in {
            "owner": str(self.creator.pk),
            "role": "assistant",
            "run": str(uuid4()),
            "sequence": 99,
            "status": "completed",
            "format": "html",
        }.items():
            await socket.send_json_to(
                {
                    "type": "chat.message",
                    "conversation_id": self.conversation_id,
                    "message": "Forged input",
                    field: value,
                }
            )
            rejected = await socket.receive_json_from(timeout=5)
            self.assertEqual(rejected["type"], "protocol.error")
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
        await database_sync_to_async(self.assert_owned_runtime)()

    def assert_owned_runtime(self) -> None:
        """Check actor identity and durable provider output after the socket succeeds."""
        conversation = AIConversation.objects.get(pk=self.conversation_id)
        run = AIRun.objects.get(conversation=conversation)
        self.assertEqual(conversation.owner_id, self.user.pk)
        self.assertEqual(conversation.created_by_id, self.user.pk)
        self.assertEqual(run.initiated_by_id, self.user.pk)
        self.assertEqual(run.status, "completed")
        context, image = conversation.messages_to_runtime_messages(through_sequence=1)[
            0
        ].content[1:]
        self.assertEqual(context.type, "text")
        self.assertIn(str(self.todo.pk), context.text)
        self.assertIn("Context from the workspace", context.text)
        self.assertNotIn('"priority"', context.text)
        self.assertIn(str(self.image.pk), image.text)
        self.assertEqual(
            conversation.messages.get(role="assistant").content_blocks[0]["text"],
            "Hello from the agent.",
        )

    def revoke(self) -> None:
        """Remove use authorization while the original socket remains connected."""
        self.grant.all_authenticated_users = False
        self.grant.save(update_fields=["all_authenticated_users"])
