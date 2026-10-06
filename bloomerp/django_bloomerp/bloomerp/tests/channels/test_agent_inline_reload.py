"""Verify page disconnect/reconnect does not own or cancel inline agent execution."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import partial
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from channels.db import database_sync_to_async
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

from bloomerp.agents.controller import AgentController
from bloomerp.agents.runtime import (
    AgentRuntimeConfig,
    AgentRuntimeCredentials,
    AgentRuntimeRunRequest,
)
from bloomerp.agents.runtimes.pydantic_ai import PydanticAIRuntime
from bloomerp.channels.agents.agent_consumer import AgentConsumer
from bloomerp.models import User
from bloomerp.models.agents import AIRun
from bloomerp.router import BloomerpRouteRegistry
from bloomerp.tests.agents.test_controller import configure_test_agent
from bloomerp.tests.base import (
    BloomerpChannelTestCase,
    ChannelAction,
    ChannelContext,
    ChannelScenario,
    Connect,
    Disconnect,
    ExpectJson,
)


@dataclass
class ReloadGate:
    """Hold a real SDK response open while the requesting browser goes away."""

    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False
    before_text: bool = False

    async def stream(
        self, messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        """Stream text on both sides of a browser reload without using an external provider."""
        if not self.before_text:
            yield "**Before refresh** "
        self.started.set()
        try:
            await asyncio.wait_for(self.release.wait(), timeout=5)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.before_text:
            yield "**Before refresh** "
        yield "and after refresh."


_current_gate: ReloadGate | None = None


def reload_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Bind the real PydanticAI adapter to the currently controlled offline response."""
    assert _current_gate is not None
    return FunctionModel(stream_function=_current_gate.stream)


def reload_runtime(config: AgentRuntimeConfig) -> PydanticAIRuntime:
    """Use production runtime ownership and cancellation behavior with an offline model."""
    return PydanticAIRuntime(model_factory=reload_model)


class AgentInlineReloadTests(BloomerpChannelTestCase):
    """Exercise real controller dispatch, consumer disconnect, snapshots and ordered replay."""

    def setUp(self) -> None:
        """Create an authorized actor and force the production inline dispatch path."""
        super().setUp()
        self.user = User.objects.create_user(username="inline-reload-owner")
        self.agent = configure_test_agent(self.user, reload_runtime)
        self.registry = BloomerpRouteRegistry()
        self.registry.register(path="ws/agents/<uuid:tab_id>/", route_type="websocket")(
            AgentConsumer
        )
        inline = patch.object(AgentController, "worker_mode", return_value=False)
        inline.start()
        self.addCleanup(inline.stop)

    def get_test_scenarios(self) -> list[ChannelScenario]:
        """Declare refresh during execution and completion while no browser is connected."""
        scenarios = []
        for finish_offline, before_text in (
            (False, False),
            (True, False),
            (False, True),
        ):
            path = f"/ws/agents/{uuid4()}/"
            steps = [
                ChannelAction(
                    name="Start a fresh controlled response",
                    execute=partial(self.initialize_gate, before_text=before_text),
                ),
                Connect(
                    path=path,
                    user=self.user,
                    headers=[(b"host", b"erp.test"), (b"origin", b"https://erp.test")],
                ),
                ExpectJson(validators=[self.connection_ready]),
                ChannelAction(
                    name="Submit and wait for committed partial text",
                    execute=self.submit_and_wait,
                ),
                Disconnect(),
                ChannelAction(
                    name="Disconnect leaves one live inline attempt",
                    execute=self.assert_still_running,
                ),
            ]
            if finish_offline:
                steps.append(
                    ChannelAction(
                        name="Complete with no connected browser",
                        execute=self.complete_offline,
                    )
                )
            steps.extend(
                [
                    Connect(
                        path=path,
                        user=self.user,
                        socket="reloaded",
                        headers=[
                            (b"host", b"erp.test"),
                            (b"origin", b"https://erp.test"),
                        ],
                    ),
                    ExpectJson(socket="reloaded", validators=[self.connection_ready]),
                    ChannelAction(
                        name="Restore the persisted conversation",
                        execute=self.restore_snapshot,
                    ),
                ]
            )
            if not finish_offline:
                steps.append(
                    ChannelAction(
                        name="Continue streaming to the new browser",
                        execute=self.complete_live,
                    )
                )
            steps.append(
                ChannelAction(
                    name="Replay completion without new attempts or duplicate input",
                    execute=self.verify_replay,
                )
            )
            scenarios.append(
                ChannelScenario(
                    name="Refresh before the first response text"
                    if before_text
                    else "Refresh after offline completion"
                    if finish_offline
                    else "Refresh while inline response is active",
                    steps=steps,
                )
            )
        return scenarios

    async def initialize_gate(
        self, context: ChannelContext, *, before_text: bool = False
    ) -> None:
        """Create synchronization on the scenario's event loop before dispatch starts."""
        global _current_gate
        self.gate = ReloadGate(before_text=before_text)
        _current_gate = self.gate
        self.snapshot_cursor = 0

    def connection_ready(self, message: Any) -> bool:
        """Recognize the authenticated browser's connection acknowledgement."""
        return message.get("type") == "connection.ready"

    async def submit_and_wait(self, context: ChannelContext) -> None:
        """Capture accepted identifiers and the first committed streamed fragment."""
        self.client_message_id = uuid4()
        browser = context.sockets["default"]
        await browser.send_json_to(
            {
                "type": "chat.message",
                "message": "Continue across refresh",
                "agent_id": str(self.agent.pk),
                "client_message_id": str(self.client_message_id),
            }
        )
        accepted = streamed = False
        for _ in range(20):
            message = await browser.receive_json_from(timeout=3)
            if (
                message.get("status") == "accepted"
                and message.get("action") == "chat.message"
            ):
                self.run_id = UUID(message["run_id"])
                self.conversation_id = UUID(message["conversation_id"])
                accepted = True
            if message.get("event_type") == "text.delta":
                self.assertEqual(message["delta"], "**Before refresh** ")
                streamed = True
            if accepted and (streamed or self.gate.before_text):
                break
        self.assertTrue(accepted and (streamed or self.gate.before_text))
        await asyncio.wait_for(self.gate.started.wait(), timeout=3)

    def run_state(self) -> dict[str, Any]:
        """Inspect durable execution ownership and transcript without relying on socket state."""
        run = AIRun.objects.get(pk=self.run_id)
        return {
            "status": run.status,
            "cancel_requested": run.cancel_requested_at,
            "attempts": list(run.attempts.values("status", "execution_mode")),
            "user_messages": run.conversation.messages.filter(role="user").count(),
            "text": "".join(
                block["text"]
                for message in run.messages.filter(role="assistant").order_by(
                    "sequence"
                )
                for block in message.content_blocks
                if block["type"] == "text"
            ),
        }

    async def assert_still_running(self, context: ChannelContext) -> None:
        """Verify closing the original ASGI application did not cancel its independent task."""
        state = await database_sync_to_async(self.run_state)()
        self.assertEqual(state["status"], "running")
        self.assertEqual(
            state["attempts"], [{"status": "running", "execution_mode": "inline"}]
        )
        self.assertIsNone(state["cancel_requested"])
        self.assertFalse(self.gate.cancelled)

    async def wait_completed(self) -> None:
        """Wait briefly for final persistence after releasing the offline provider response."""
        async with asyncio.timeout(3):
            while (await database_sync_to_async(self.run_state)())[
                "status"
            ] != "completed":
                await asyncio.sleep(0.01)

    async def complete_offline(self, context: ChannelContext) -> None:
        """Finish inline execution while every browser subscription is disconnected."""
        self.gate.release.set()
        await self.wait_completed()

    async def restore_snapshot(self, context: ChannelContext) -> None:
        """Fetch the same owner-authorized transcript used by the chat after page reload."""
        browser = context.sockets["reloaded"]
        await browser.send_json_to(
            {
                "type": "chat.conversation",
                "conversation_id": str(self.conversation_id),
                "request_id": str(uuid4()),
            }
        )
        message = await browser.receive_json_from(timeout=3)
        self.assertEqual(message["status"], "conversation")
        self.snapshot_cursor = message["run"]["cursor"]
        self.snapshot_text = "".join(
            block["text"]
            for row in message["messages"]
            if row["role"] == "assistant"
            for block in row["content"]
            if block["type"] == "text"
        )
        self.assertEqual(
            message["run"]["status"],
            (await database_sync_to_async(self.run_state)())["status"],
        )
        if self.gate.before_text:
            self.assertEqual(self.snapshot_text, "")
        else:
            self.assertTrue(self.snapshot_text.startswith("**Before refresh** "))

    async def complete_live(self, context: ChannelContext) -> None:
        """Observe the rest of the original response through the newly subscribed socket."""
        self.gate.release.set()
        text = self.snapshot_text
        for _ in range(20):
            event = await context.sockets["reloaded"].receive_json_from(timeout=3)
            if event.get("event_type") == "text.delta":
                self.assertGreater(event["sequence"], self.snapshot_cursor)
                text += event["delta"]
            if event.get("event_type") == "run.completed":
                break
        self.assertEqual(text, "**Before refresh** and after refresh.")
        await self.wait_completed()

    async def verify_replay(self, context: ChannelContext) -> None:
        """Prove reconnection needs only snapshots and replay, with one unchanged run attempt."""
        browser = context.sockets["reloaded"]
        await browser.send_json_to(
            {
                "type": "chat.replay",
                "conversation_id": str(self.conversation_id),
                "run_id": str(self.run_id),
                "after_sequence": 0,
                "limit": 100,
            }
        )
        message = await browser.receive_json_from(timeout=3)
        self.assertEqual(message["status"], "replay")
        events = message["events"]
        sequences = [event["sequence"] for event in events]
        self.assertEqual(sequences, sorted(set(sequences)))
        self.assertEqual(events[-1]["event_type"], "run.completed")
        self.assertEqual(
            "".join(
                event["payload"]["text"]
                for event in events
                if event["event_type"] == "text.delta"
            ),
            "**Before refresh** and after refresh.",
        )
        state = await database_sync_to_async(self.run_state)()
        self.assertEqual(
            state["attempts"], [{"status": "completed", "execution_mode": "inline"}]
        )
        self.assertEqual(state["user_messages"], 1)
        self.assertIsNone(state["cancel_requested"])
        self.assertFalse(self.gate.cancelled)
