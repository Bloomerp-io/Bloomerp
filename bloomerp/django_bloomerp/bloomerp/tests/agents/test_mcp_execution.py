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
    AgentConversationEdit,
)
from bloomerp.agents.mcp import LocalMcpClient, McpToolCoordinator
from bloomerp.agents.resource_access import resource_tool_name
from bloomerp.agents.runtime import (
    AgentRuntimeConfig,
    AgentRuntimeCredentials,
    AgentRuntimeRunRequest,
    AgentRuntimeToolProposal,
)
from bloomerp.agents.runtimes.pydantic_ai import PydanticAIRuntime
from bloomerp.mcp.definition import McpResource, McpTool
from bloomerp.mcp.view import McpEndpointView
from bloomerp.models.agents import AIApproval, AIRun, AIToolCall
from bloomerp.router import BloomerpRouteRegistry, router
from bloomerp.tests.agents.test_controller import (
    OPTIONS,
    agent_test_config,
    configure_test_agent,
)
from bloomerp.tests.base import BloomerpChannelTestCase
from bloomerp.tests.mcp.test_resources import guide_reader

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


async def resource_stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
    """Read an advertised guide and verify its embedded content reaches model history."""
    returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
    if returns:
        result = returns[-1].content
        assert result["content"][0]["resource"]["uri"] == "bloomerp://tests/runtime-guide"
        assert "Guide for user" in result["content"][0]["resource"]["text"]
        yield "Guide read."
    else:
        yield {0: DeltaToolCall(name=resource_tool_name("bloomerp://tests/runtime-guide"), json_args="{}", tool_call_id="read-guide")}


def tool_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Provide a network-free tool-calling model to the production runtime."""
    return FunctionModel(stream_function=tool_stream)


def tool_runtime(config: AgentRuntimeConfig) -> PydanticAIRuntime:
    """Construct the real runtime for persisted approval integration tests."""
    return PydanticAIRuntime(model_factory=tool_model)


@override_settings(
    BLOOMERP_CONFIG=agent_test_config(
        {
            **OPTIONS,
            "runtime_factory": "bloomerp.tests.agents.test_mcp_execution.tool_runtime",
        }
    ),
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
        self.ai_agent = configure_test_agent(self.user, tool_runtime)
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
        self.enterContext(patch.object(router, "get_mcp_resources", return_value=[]))
        self.enterContext(patch.object(router, "get_mcp_resource_templates", return_value=[]))
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

    def test_resource_read_runs_through_model_and_persists_content(self) -> None:
        """Complete a real runtime resource call without a write approval or losing content."""
        registry = BloomerpRouteRegistry()
        registry.register(name="Runtime guide", mcp=McpResource(uri="bloomerp://tests/runtime-guide"))(guide_reader)
        with patch.object(router, "get_mcp_resources", return_value=registry.routes), patch(
            "bloomerp.tests.agents.test_mcp_execution.tool_model",
            return_value=FunctionModel(stream_function=resource_stream),
        ):
            run = self.new_run()
            self.execute(run)
        self.assertEqual(run.status, "completed", run.error)
        self.assertFalse(AIApproval.objects.filter(tool_call__run=run).exists())
        tool = run.tool_calls.get()
        self.assertEqual(tool.status, "completed")
        self.assertIn(f"Guide for user {self.user.pk}", tool.result["content"][0]["resource"]["text"])

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

    def test_agent_selection_filters_live_catalog_and_direct_dispatch(self) -> None:
        """Allow all by default, then expose only selected registered tools and enforce calls."""
        client = LocalMcpClient(self.user.pk, "https://erp.test", str(self.ai_agent.pk))
        self.assertEqual([item.identifier for item in client.definitions()], ["fixture_effect"])
        self.ai_agent.internal_tool_mode = "selected"
        self.ai_agent.internal_tools = []
        self.ai_agent.save()
        self.assertEqual(client.definitions(), ())
        with self.assertRaisesMessage(PermissionDenied, "not allowed"):
            client.request("tools/call", {"name": "fixture_effect", "arguments": {"value": 4}})
        self.assertEqual(EFFECTS, [])
        self.ai_agent.internal_tools = ["fixture_effect", "deleted_tool"]
        self.ai_agent.save()
        self.assertEqual([item.identifier for item in client.definitions()], ["fixture_effect"])
        self.user.is_staff = False
        self.user.save()
        result = client.request("tools/call", {"name": "fixture_effect", "arguments": {"value": 4}})
        self.assertTrue(result["isError"])
        self.assertEqual(EFFECTS, [])

    def test_agent_revocation_refuses_stale_approved_call(self) -> None:
        """Reload agent restrictions on approval resume even though the run snapshot predates them."""
        run = self.new_run()
        self.execute(run)
        approval = AIApproval.objects.get(tool_call__run=run)
        async_to_sync(self.controller.decide_approval)(
            AgentApprovalDecision(approval_id=approval.pk, decision="approved")
        )
        self.ai_agent.internal_tool_mode = "selected"
        self.ai_agent.internal_tools = []
        self.ai_agent.save()
        self.execute(run)
        self.assertEqual(run.status, "failed", run.error)
        self.assertEqual(EFFECTS, [])

    def test_registered_extensions_are_discovered_without_static_choices(self) -> None:
        """Refresh labels and runtime definitions after extension registration and removal."""
        from bloomerp.agents.tool_access import internal_tool_choices

        client = LocalMcpClient(self.user.pk, "https://erp.test", str(self.ai_agent.pk))
        self.assertEqual(len(client.definitions()), 1)
        registry = BloomerpRouteRegistry()
        registry.register(
            name="Extension result", url_name="extension_result", route_type="mcp",
            mcp=McpTool(input_schema={"type": "object"}, title="Extension result", read_only_hint=True),
        )(typed_result)
        live_routes = router.get_mcp_routes()
        live_routes.extend(registry.routes)
        self.assertEqual({item.identifier for item in client.definitions()}, {"fixture_effect", "extension_result"})
        self.assertIn(("extension_result", "Extension result (extension_result)"), internal_tool_choices())
        self.ai_agent.internal_tool_mode = "selected"
        self.ai_agent.internal_tools = ["extension_result"]
        self.ai_agent.save()
        self.assertEqual([item.identifier for item in client.definitions()], ["extension_result"])
        live_routes.remove(registry.routes[0])
        self.assertEqual(client.definitions(), ())

    def test_crafted_proposal_is_refused_with_unfiltered_client(self) -> None:
        """Enforce the run's agent even when a caller supplies a client with unrestricted discovery."""
        run = self.new_run()
        attempt = run.create_attempt(
            execution_mode="inline", executor_id="test", lease_duration=timedelta(minutes=1)
        )
        definition = self.client.definitions()[0]
        self.ai_agent.internal_tool_mode = "selected"
        self.ai_agent.internal_tools = []
        self.ai_agent.save()
        proposal = AgentRuntimeToolProposal(
            provider_call_id="crafted-call", tool_identifier=definition.identifier,
            tool_version=definition.version, arguments={"value": 4},
        )
        with self.assertRaisesMessage(PermissionDenied, "not allowed"):
            McpToolCoordinator(run, attempt, self.client).execute(proposal)
        self.assertFalse(run.tool_calls.exists())
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
        run = self.new_run()
        run.conversation.approval_rules = {"default": "never"}
        run.conversation.save()
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

    def test_conversation_approval_changes_apply_to_next_tool_in_active_run(
        self,
    ) -> None:
        """Read live rules for each proposal and retain decisions on already pending approvals."""
        from uuid import uuid4

        run = self.new_run()
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="test",
            lease_duration=timedelta(minutes=1),
        )
        coordinator = McpToolCoordinator(run, attempt, self.client)
        definition = self.client.definitions()[0]
        proposal = AgentRuntimeToolProposal(
            provider_call_id="pending-change",
            tool_identifier=definition.identifier,
            tool_version=definition.version,
            arguments={"value": 7},
        )
        first = coordinator.execute(proposal)
        self.assertEqual(first.status, "waiting")
        self.controller.edit_conversation(
            AgentConversationEdit(
                request_id=uuid4(),
                conversation_id=run.conversation_id,
                approval_rules={"default": "never"},
            )
        )
        # Existing pending approval is still binding after disabling new approvals.
        self.assertEqual(coordinator.execute(proposal).status, "waiting")
        second = coordinator.execute(
            proposal.model_copy(update={"provider_call_id": "new-change"})
        )
        self.assertEqual(second.status, "completed")
        self.assertEqual(EFFECTS, [7])
        self.controller.edit_conversation(
            AgentConversationEdit(
                request_id=uuid4(),
                conversation_id=run.conversation_id,
                approval_rules={"default": "always"},
            )
        )
        third = coordinator.execute(
            proposal.model_copy(update={"provider_call_id": "require-again"})
        )
        self.assertEqual(third.status, "waiting")
        self.assertEqual(EFFECTS, [7])
