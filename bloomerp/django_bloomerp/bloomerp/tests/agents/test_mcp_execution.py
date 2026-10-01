"""Verify MCP parity, durable approval resumes and effects with offline models."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest
from django.test import override_settings
from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from bloomerp.agents.controller import (
    AgentApprovalDecision,
    AgentChatRequest,
    AgentController,
)
from bloomerp.agents.mcp import LocalMcpClient, McpToolCoordinator
from bloomerp.agents.pydantic_ai import PydanticAIRuntime
from bloomerp.agents.runtime import (
    AgentRuntimeCredentials,
    AgentRuntimeRunRequest,
    AgentRuntimeToolProposal,
)
from bloomerp.mcp.definition import McpTool
from bloomerp.mcp.view import McpEndpointView
from bloomerp.models.agents import AIApproval, AIRun, AIToolCall
from bloomerp.router import BloomerpRouteRegistry, router
from bloomerp.tests.agents.test_controller import OPTIONS, agent_test_config
from bloomerp.tests.base import BloomerpChannelTestCase

EFFECTS: list[int] = []


def gated_effect(request: HttpRequest) -> dict[str, Any] | Response:
    """Apply a fixture effect only when the current endpoint actor is staff."""
    if not request.user.is_staff:
        return Response({"detail": "Forbidden"}, status=403)
    EFFECTS.append(request.data["value"])
    return {"value": request.data["value"]}


def typed_result(request: HttpRequest) -> Response:
    """Return SQL-like Python values that only become JSON through HTTP rendering."""
    return Response(
        {
            "rows": [
                {
                    "date_of_birth": date(1990, 1, 2),
                    "updated_at": datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
                    "id": UUID("1c31ffae-70e7-4042-975b-bde33b6f361c"),
                    "amount": Decimal("12.50"),
                    "optional": None,
                    "active": True,
                }
            ]
        }
    )


async def tool_stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
    """Request a genuine SDK external tool then finish after its persisted result."""
    if any(
        isinstance(part, ToolReturnPart)
        for message in messages
        for part in message.parts
    ):
        yield "Action handled."
    else:
        yield {
            0: DeltaToolCall(
                name="fixture_effect", json_args='{"value":7}', tool_call_id="call-1"
            )
        }


def tool_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Provide a network-free tool-calling model to the production runtime."""
    return FunctionModel(stream_function=tool_stream)


def tool_runtime() -> PydanticAIRuntime:
    """Construct the real runtime for persisted approval integration tests."""
    return PydanticAIRuntime(model_factory=tool_model)


@override_settings(
    BLOOMERP_CONFIG=agent_test_config({
        **OPTIONS,
        "runtime_factory": "bloomerp.tests.agents.test_mcp_execution.tool_runtime",
    }),
    ALLOWED_HOSTS=["erp.test", "localhost"],
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class McpExecutionTests(BloomerpChannelTestCase):
    """Exercise the actual MCP view, controller, models and SDK without external effects."""

    def setUp(self) -> None:
        """Install a deterministic permission-gated mutation through the MCP registry."""
        EFFECTS.clear()
        self.user = get_user_model().objects.create_user(
            username="mcp-owner", is_staff=True
        )
        self.other = get_user_model().objects.create_user(username="mcp-other")
        self.controller = AgentController(self.user, origin="https://erp.test")
        self.client = LocalMcpClient(self.user.pk, "https://erp.test")
        registry = BloomerpRouteRegistry()
        registry.register(
            name="Fixture effect",
            url_name="fixture_effect",
            route_type="mcp",
            mcp=McpTool(
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                read_only_hint=False,
                destructive_hint=True,
            ),
        )(gated_effect)
        self.enterContext(
            patch.object(router, "get_mcp_routes", return_value=registry.routes)
        )
        self.enterContext(patch.object(self.controller, "schedule_dispatch"))

    def test_local_result_matches_rendered_http_and_persists(self) -> None:
        """Keep typed SQL results identical locally and over HTTP through durable completion."""
        registry = BloomerpRouteRegistry()
        registry.register(
            name="Typed fixture",
            url_name="fixture_effect",
            route_type="mcp",
            mcp=McpTool(input_schema={"type": "object"}, read_only_hint=True),
        )(typed_result)
        with patch.object(router, "get_mcp_routes", return_value=registry.routes):
            params = {"name": "fixture_effect", "arguments": {"value": 7}}
            request = APIRequestFactory().post(
                "/mcp/",
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
                format="json",
                HTTP_HOST="erp.test",
                secure=True,
                HTTP_ACCEPT="application/json, text/event-stream",
                HTTP_MCP_PROTOCOL_VERSION="2025-11-25",
            )
            force_authenticate(request, user=self.user)
            response = McpEndpointView.as_view()(request)
            response.render()
            expected = json.loads(response.content)["result"]
            local = self.client.request("tools/call", params)
            self.assertEqual(local, expected)
            row = local["structuredContent"]["rows"][0]
            self.assertEqual(row["date_of_birth"], "1990-01-02")
            self.assertEqual(row["updated_at"], "2026-09-30T12:00:00Z")
            self.assertEqual(row["id"], "1c31ffae-70e7-4042-975b-bde33b6f361c")
            self.assertEqual(row["amount"], 12.5)
            self.assertEqual(
                json.loads(local["content"][0]["text"]), local["structuredContent"]
            )
            run = self.new_run()
            self.execute(run)
            self.assertEqual(run.status, "completed", run.error)
            self.assertEqual(run.tool_calls.get().result, expected)

    def new_run(self) -> AIRun:
        """Accept a real message and return its durable queued execution."""
        submission = self.controller.accept_message(
            AgentChatRequest(content=[{"type": "text", "text": "Do it"}])
        )
        return AIRun.objects.get(pk=submission.run_id)

    def execute(self, run: AIRun) -> None:
        """Run one real inline attempt and refresh its persisted status."""
        async_to_sync(self.controller.run_attempt)(
            run.pk, execution_mode="inline", executor_id="test"
        )
        run.refresh_from_db()

    def test_approval_pause_resume_and_duplicate_delivery(self) -> None:
        """Pause without effects, approve, resume once and preserve the exact MCP result."""
        run = self.new_run()
        self.execute(run)
        self.assertEqual(run.status, "waiting", run.error)
        self.assertEqual(EFFECTS, [])
        approval = AIApproval.objects.get(tool_call__run=run)
        outcome = run.events.get(event_type="tool.outcome")
        self.assertEqual(
            outcome.payload["data"]["approvals"][0]["tool_title"],
            "Fixture effect",
        )
        self.assertEqual(
            run.conversation.transcript_page()["approvals"][0]["tool_title"],
            "Fixture effect",
        )
        decision = AgentApprovalDecision(approval_id=approval.pk, decision="approved")
        async_to_sync(self.controller.decide_approval)(decision)
        async_to_sync(self.controller.decide_approval)(decision)
        self.execute(run)
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(run.attempts.count(), 2)
        self.assertEqual(EFFECTS, [7])
        self.assertEqual(run.tool_calls.get().result["structuredContent"], {"value": 7})
        self.execute(run)
        self.assertEqual(EFFECTS, [7])

    def test_rejection_is_returned_to_model_without_execution(self) -> None:
        """Resolve a refusal as a tool outcome so the assistant can explain it."""
        run = self.new_run()
        self.execute(run)
        approval = AIApproval.objects.get(tool_call__run=run)
        async_to_sync(self.controller.decide_approval)(
            AgentApprovalDecision(approval_id=approval.pk, decision="rejected")
        )
        self.execute(run)
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(run.tool_calls.get().status, "rejected")
        self.assertEqual(EFFECTS, [])

    def test_read_only_tools_run_without_approval(self) -> None:
        """Use the existing MCP annotation to run read-only calls without pausing."""
        route = router.get_mcp_routes()[0]
        route.mcp.read_only_hint = True
        route.mcp.destructive_hint = False
        run = self.new_run()
        self.execute(run)
        self.assertEqual(run.status, "completed", run.error)
        self.assertFalse(AIApproval.objects.exists())
        self.assertEqual(EFFECTS, [7])

    def test_changed_contract_invalidates_pending_approval(self) -> None:
        """Reject execution when the advertised MCP contract differs from the approved snapshot."""
        run = self.new_run()
        self.execute(run)
        approval = AIApproval.objects.get(tool_call__run=run)
        async_to_sync(self.controller.decide_approval)(
            AgentApprovalDecision(approval_id=approval.pk, decision="approved")
        )
        router.get_mcp_routes()[0].mcp.description = "Changed tool contract"
        self.execute(run)
        self.assertEqual(run.status, "failed")
        self.assertEqual(EFFECTS, [])

    def test_permission_revocation_after_approval(self) -> None:
        """Re-enter the endpoint with fresh permissions even after a valid approval."""
        run = self.new_run()
        self.execute(run)
        approval = AIApproval.objects.get(tool_call__run=run)
        async_to_sync(self.controller.decide_approval)(
            AgentApprovalDecision(approval_id=approval.pk, decision="approved")
        )
        get_user_model().objects.filter(pk=self.user.pk).update(is_staff=False)
        self.execute(run)
        self.assertEqual(run.status, "completed", run.error)
        self.assertTrue(run.tool_calls.get().result["isError"])
        self.assertEqual(EFFECTS, [])

    def test_foreign_approval_and_cancelled_run_are_rejected(self) -> None:
        """Reject cross-owner decisions and decisions after durable cancellation."""
        run = self.new_run()
        self.execute(run)
        decision = AgentApprovalDecision(
            approval_id=AIApproval.objects.get().pk, decision="approved"
        )
        with self.assertRaises(PermissionDenied):
            AgentController(self.other).record_approval(decision)
        run.request_cancel()
        with self.assertRaises(ValidationError):
            self.controller.record_approval(decision)
        self.assertEqual(EFFECTS, [])

    def test_catalog_contract_parity_and_cached_results(self) -> None:
        """Keep MCP names/schemas/results exact and do not execute a completed proposal twice."""
        item = self.client.catalog()["fixture_effect"]
        definition = self.client.definitions()[0]
        self.assertEqual(definition.input_schema, item["inputSchema"])
        self.assertEqual(definition.annotations, item["annotations"])
        with override_settings(
            BLOOMERP_CONFIG=agent_test_config({
                **OPTIONS,
                "config": {**OPTIONS["config"], "approval_rules": {"default": "never"}},
            })
        ):
            run = self.new_run()
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="test",
            lease_duration=timedelta(minutes=1),
        )
        coordinator = McpToolCoordinator(run, attempt, self.client)
        proposal = AgentRuntimeToolProposal(
            provider_call_id="once",
            tool_identifier=definition.identifier,
            tool_version=definition.version,
            arguments={"value": 9},
        )
        first = coordinator.execute(proposal)
        second = coordinator.execute(proposal)
        self.assertEqual(first, second)
        self.assertEqual(EFFECTS, [9])
        with self.assertRaises(ValidationError):
            coordinator.execute(
                proposal.model_copy(update={"arguments": {"value": 10}})
            )

    def test_uncertain_dispatch_is_not_repeated(self) -> None:
        """A crash after dispatch cannot silently replay a potentially committed mutation."""
        run = self.new_run()
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="test",
            lease_duration=timedelta(minutes=1),
        )
        definition = self.client.definitions()[0]
        proposal = AgentRuntimeToolProposal(
            provider_call_id="lost",
            tool_identifier=definition.identifier,
            tool_version=definition.version,
            arguments={"value": 2},
        )
        _tool, dispatch = AIToolCall.prepare(
            run, attempt.lease_token, proposal, requires_approval=False
        )
        self.assertTrue(dispatch)
        outcome = McpToolCoordinator(run, attempt, self.client).execute(proposal)
        self.assertEqual(outcome.error.code, "tool_outcome_unknown")
        self.assertEqual(EFFECTS, [])

    def test_async_proposal_returns_pending_approval(self) -> None:
        """Prepare the first proposal through the async production coordinator."""
        run = self.new_run()
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="test",
            lease_duration=timedelta(minutes=1),
        )
        definition = self.client.definitions()[0]
        proposal = AgentRuntimeToolProposal(
            provider_call_id="async",
            tool_identifier=definition.identifier,
            tool_version=definition.version,
            arguments={"value": 2},
        )
        outcome = async_to_sync(McpToolCoordinator(run, attempt, self.client).call)(
            proposal
        )
        self.assertEqual(outcome.status, "waiting")

    async def test_websocket_approval_resumes_and_replays(self) -> None:
        """Complete an approval through the public socket and replay its durable decision."""
        from channels.db import database_sync_to_async
        from channels.routing import URLRouter
        from channels.testing import WebsocketCommunicator
        from django.urls import path

        from bloomerp.channels.agents.agent_consumer import AgentConsumer

        application = URLRouter(
            [path("ws/agents/<uuid:tab_id>/", AgentConsumer.as_asgi())]
        )
        browser = WebsocketCommunicator(
            application,
            f"/ws/agents/{uuid4()}/",
            headers=[(b"host", b"erp.test"), (b"origin", b"https://erp.test")],
        )
        browser.scope["user"] = self.user
        connected, _ = await browser.connect()
        self.assertTrue(connected)
        try:
            await browser.receive_json_from()
            await browser.send_json_to(
                {
                    "type": "chat.message",
                    "message": "Do it",
                    "client_message_id": str(uuid4()),
                }
            )
            accepted = await browser.receive_json_from(timeout=5)
            approval_id = None
            for _ in range(50):
                event = await browser.receive_json_from(timeout=5)
                self.assertNotEqual(event.get("status"), "failed", event)
                if event.get("event_type") == "tool.outcome":
                    approval_id = event["payload"]["data"]["approvals"][0]["id"]
                if event.get("status") == "paused":
                    break
            self.assertIsNotNone(approval_id)
            self.assertEqual(EFFECTS, [])
            await browser.send_json_to(
                {
                    "type": "chat.approval",
                    "approval_id": approval_id,
                    "decision": "approved",
                }
            )
            completed = False
            for _ in range(50):
                event = await browser.receive_json_from(timeout=5)
                self.assertNotEqual(event.get("status"), "failed", event)
                if event.get("status") == "completed":
                    completed = True
                    break
            self.assertTrue(completed)
            self.assertEqual(EFFECTS, [7])
            await browser.send_json_to(
                {
                    "type": "chat.replay",
                    "conversation_id": accepted["conversation_id"],
                    "run_id": accepted["run_id"],
                }
            )
            replay = await browser.receive_json_from(timeout=5)
            self.assertTrue(
                any(
                    item["event_type"] == "approval.decided"
                    for item in replay["events"]
                )
            )
            self.assertEqual(
                await database_sync_to_async(AIToolCall.objects.count)(), 1
            )
        finally:
            await browser.disconnect()
