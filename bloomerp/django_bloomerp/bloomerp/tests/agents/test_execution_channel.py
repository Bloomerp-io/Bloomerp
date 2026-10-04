"""Exercise the actual WebSocket/controller/database/runtime path without API calls."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import path
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

from bloomerp.agents.runtime import (
    AgentRuntimeConfig,
    AgentRuntimeCredentials,
    AgentRuntimeRunRequest,
)
from bloomerp.agents.runtimes.pydantic_ai import PydanticAIRuntime
from bloomerp.channels.agents.agent_consumer import AgentConsumer
from bloomerp.models.agents import AIMessage, AIRun
from bloomerp.tests.agents.test_controller import (
    agent_test_config,
    configure_test_agent,
    offline_runtime,
)
from bloomerp.tests.base import BloomerpChannelTestCase


async def slow_stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str]:
    """Leave a provider request open so cancellation must interrupt active execution."""
    yield "Partial text"
    await asyncio.sleep(60)
    yield "Should not appear"


def slow_factory(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Select an offline provider stream that waits for controller cancellation."""
    return FunctionModel(stream_function=slow_stream)


def slow_runtime(config: AgentRuntimeConfig) -> PydanticAIRuntime:
    """Construct the real runtime around a deliberately suspended SDK stream."""
    return PydanticAIRuntime(model_factory=slow_factory)


@override_settings(
    BLOOMERP_CONFIG=agent_test_config(),
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class AgentExecutionChannelTests(BloomerpChannelTestCase):
    """Verify public events follow committed writes and cancellation leaves partial history."""

    def setUp(self) -> None:
        """Create one authenticated owner for the real channel application."""
        self.user = get_user_model().objects.create_user(username="socket-owner")
        factory = (
            slow_runtime
            if self._testMethodName
            == "test_cancel_interrupts_provider_and_persists_partial_state"
            else offline_runtime
        )
        configure_test_agent(self.user, factory)

    async def browser(self) -> WebsocketCommunicator:
        """Connect an authenticated fixture tab using the real consumer route."""
        app = URLRouter([path("ws/agents/<uuid:tab_id>/", AgentConsumer.as_asgi())])
        browser = WebsocketCommunicator(
            app,
            f"/ws/agents/{uuid4()}/",
            headers=[(b"host", b"erp.test"), (b"origin", b"https://erp.test")],
        )
        browser.scope["user"] = self.user
        connected, _ = await browser.connect()
        self.assertTrue(connected)
        await browser.receive_json_from()
        return browser

    def assert_committed(self, event: dict[str, Any]) -> None:
        """Check a delivered delta already exists in an owned persisted message/event."""
        message = AIMessage.objects.get(pk=event["message_id"])
        self.assertEqual(message.conversation.owner_id, self.user.pk)
        self.assertIn(event["delta"], message.content_blocks[0]["text"])
        self.assertTrue(message.run.events.filter(sequence=event["sequence"]).exists())

    async def test_live_text_delivery_and_replay(self) -> None:
        """Receive persisted incremental output and replay the completed run without checkpoints."""
        browser = await self.browser()
        try:
            message_id = str(uuid4())
            await browser.send_json_to(
                {
                    "type": "chat.message",
                    "message": "Hello",
                    "client_message_id": message_id,
                }
            )
            accepted = await browser.receive_json_from(timeout=5)
            self.assertEqual(accepted["status"], "accepted")
            self.assertEqual(accepted["client_message_id"], message_id)
            text = []
            for _ in range(100):
                event = await browser.receive_json_from(timeout=5)
                self.assertNotEqual(event.get("event_type"), "checkpoint.created")
                if event["status"] == "streaming":
                    await database_sync_to_async(self.assert_committed)(event)
                    text.append(event["delta"])
                if event["status"] in {"failed", "completed"}:
                    self.assertEqual(event["status"], "completed", event)
                    break
            else:
                self.fail("No terminal response")
            self.assertEqual("".join(text), "Hello from the agent.")
            await browser.send_json_to(
                {
                    "type": "chat.replay",
                    "run_id": accepted["run_id"],
                    "conversation_id": accepted["conversation_id"],
                }
            )
            replay = await browser.receive_json_from()
            self.assertEqual(replay["status"], "replay")
            self.assertEqual(replay["events"][-1]["event_type"], "run.completed")
        finally:
            await browser.disconnect()

    async def test_cancel_interrupts_provider_and_persists_partial_state(self) -> None:
        """Cancel after visible output while the provider is stalled, using the durable flag."""
        browser = await self.browser()
        try:
            await browser.send_json_to(
                {
                    "type": "chat.message",
                    "message": "Slow reply",
                    "client_message_id": str(uuid4()),
                }
            )
            accepted = await browser.receive_json_from(timeout=5)
            for _ in range(100):
                event = await browser.receive_json_from(timeout=5)
                if event["status"] == "streaming":
                    break
            await browser.send_json_to(
                {"type": "chat.cancel", "run_id": accepted["run_id"]}
            )
            for _ in range(100):
                event = await browser.receive_json_from(timeout=5)
                if event["status"] == "cancelled":
                    break
            else:
                self.fail("Cancellation did not complete")
            run = await database_sync_to_async(AIRun.objects.get)(pk=accepted["run_id"])
            self.assertEqual(run.status, "cancelled")
            message = await database_sync_to_async(run.messages.get)(role="assistant")
            self.assertEqual(message.status, "interrupted")
            self.assertNotIn("Should not appear", str(message.content_blocks))
        finally:
            await browser.disconnect()

    async def test_disconnect_does_not_cancel_durable_execution(self) -> None:
        """Finish accepted inline work after its originating WebSocket has closed."""
        browser = await self.browser()
        await browser.send_json_to(
            {
                "type": "chat.message",
                "message": "Continue offline",
                "client_message_id": str(uuid4()),
            }
        )
        accepted = await browser.receive_json_from(timeout=5)
        await browser.disconnect()
        for _ in range(100):
            run = await database_sync_to_async(AIRun.objects.get)(pk=accepted["run_id"])
            if run.status in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(run.status, "completed", run.error)
