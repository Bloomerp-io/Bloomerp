"""External MCP discovery and durable dispatch against mocked protocol servers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from unittest.mock import patch
from uuid import UUID

import httpx
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest
from django.test import override_settings
from django.utils import timezone
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from bloomerp.agents.controller import (
    AgentApprovalDecision,
    AgentChatRequest,
    AgentController,
)
from bloomerp.agents.external_mcp import external_tool_name, resolve_remote_binding
from bloomerp.agents.mcp import AgentMcpClient, McpToolCoordinator
from bloomerp.agents.runtime import (
    AgentRuntimeConfig,
    AgentRuntimeCredentials,
    AgentRuntimeRunRequest,
    AgentRuntimeToolProposal,
)
from bloomerp.agents.runtimes.pydantic_ai import PydanticAIRuntime
from bloomerp.mcp.definition import McpTool
from bloomerp.models.agents import AIApproval, AIRun, MCPConnection, MCPIntegration
from bloomerp.router import BloomerpRouteRegistry, router
from bloomerp.services.mcp.client import MCPUnavailableError
from bloomerp.tests.agents.test_controller import (
    OPTIONS,
    agent_test_config,
    configure_test_agent,
)
from bloomerp.tests.base import (
    BloomerpChannelTestCase,
    ChannelAction,
    ChannelContext,
    ChannelScenario,
)
from bloomerp.tests.services.mcp._server import ProtocolServer


async def external_stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
    """Call the dynamically advertised external name and finish after a durable result."""
    if any(
        isinstance(part, ToolReturnPart)
        for message in messages
        for part in message.parts
    ):
        yield "Remote action handled."
    else:
        yield {
            0: DeltaToolCall(
                name=info.function_tools[0].name,
                json_args='{"value":7}',
                tool_call_id="remote-1",
            )
        }


def fixture_internal_tool(request: HttpRequest) -> dict[str, Any]:
    """Provide an internal fixture whose original name also exists on a remote server."""
    return {"value": 7}


def external_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Supply an offline SDK model without sending credentials or data to a provider."""
    return FunctionModel(stream_function=external_stream)


def external_runtime(config: AgentRuntimeConfig) -> PydanticAIRuntime:
    """Use the production runtime and coordinator around a deterministic external tool caller."""
    return PydanticAIRuntime(model_factory=external_model)


@override_settings(
    BLOOMERP_CONFIG=agent_test_config(
        {
            **OPTIONS,
            "runtime_factory": "bloomerp.tests.agents.test_external_mcp.external_runtime",
        }
    ),
    ALLOWED_HOSTS=["erp.test", "localhost"],
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class TestExternalMcpExecution(BloomerpChannelTestCase):
    """Exercise the real controller, persistence, approval and HTTP protocol boundaries."""

    def setUp(self) -> None:
        """Configure one permitted actor, encrypted shared connection and fake remote transport."""
        self.user = get_user_model().objects.create_user(
            username="external-owner", is_staff=True
        )
        self.other = get_user_model().objects.create_user(
            username="external-other", is_staff=True
        )
        self.agent = configure_test_agent(self.user, external_runtime)
        self.agent.internal_resource_mode = "selected"
        self.agent.internal_tool_mode = "selected"
        self.agent.save()
        self.integration = MCPIntegration.objects.create(
            name="Remote tools",
            endpoint_url="https://tools.example.com/mcp",
            authentication_type="api_key",
        )
        self.connection = MCPConnection(integration=self.integration, status="ready")
        self.connection.set_credentials({"api_key": "remote-shared-secret"})
        self.connection.save()
        self.agent.mcp_integrations.add(self.integration)
        self.server = ProtocolServer()
        self.enterContext(
            patch(
                "bloomerp.services.mcp.client.PublicHTTPTransport",
                side_effect=self.transport,
            )
        )
        self.controller = AgentController(self.user, origin="https://erp.test")
        self.enterContext(patch.object(self.controller, "schedule_dispatch"))
        self.client = AgentMcpClient(
            self.user.pk, "https://erp.test", str(self.agent.pk)
        )

    def transport(self) -> httpx.MockTransport:
        """Construct an isolated stream transport while retaining production client code."""
        return httpx.MockTransport(self.server.handle)

    def new_run(self) -> AIRun:
        """Accept a genuine conversation message under the agent use grants."""
        accepted = self.controller.accept_message(
            AgentChatRequest(content=[{"type": "text", "text": "Use remote tools"}])
        )
        return AIRun.objects.get(pk=accepted.run_id)

    def execute(self, run: AIRun) -> None:
        """Execute one real inline attempt and reload its final or waiting status."""
        async_to_sync(self.controller.run_attempt)(
            run.pk, execution_mode="inline", executor_id="test"
        )
        run.refresh_from_db()

    def run_coordinator(
        self,
    ) -> tuple[AIRun, McpToolCoordinator, AgentRuntimeToolProposal]:
        """Prepare a leased run with an exact current remote definition for dispatch tests."""
        definition = self.client.definitions()[0]
        run = self.new_run()
        run.conversation.approval_rules = {"default": "never"}
        run.conversation.save()
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="test",
            lease_duration=timedelta(minutes=1),
        )
        proposal = AgentRuntimeToolProposal(
            provider_call_id="remote-1",
            tool_identifier=definition.identifier,
            tool_version=definition.version,
            arguments={"value": 7},
        )
        return run, McpToolCoordinator(run, attempt, self.client), proposal

    def assert_waiting(self, run_id: UUID) -> AIApproval:
        """Verify unannotated remote effects pause before any tools/call is sent."""
        run = AIRun.objects.get(pk=run_id)
        self.assertEqual(run.status, "waiting", run.error)
        self.assertEqual(
            run.tool_calls.get().display_title(), "Remote tools: Remote effect"
        )
        self.assertEqual(self.server.effects, [])
        return AIApproval.objects.get(tool_call__run=run)

    def assert_completed(self, run_id: UUID) -> None:
        """Verify one persisted remote effect and preserve every useful remote result field."""
        run = AIRun.objects.get(pk=run_id)
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(run.tool_calls.get().result, self.server.result)
        self.assertEqual(
            self.server.effects, [{"name": "fixture_effect", "arguments": {"value": 7}}]
        )

    async def approval_flow(self, context: ChannelContext) -> None:
        """Drive the controller through real discovery, approval pause, resume and completion."""
        run = await database_sync_to_async(self.new_run)()
        await self.controller.run_attempt(
            run.pk, execution_mode="inline", executor_id="test"
        )
        approval = await database_sync_to_async(self.assert_waiting)(run.pk)
        await self.controller.decide_approval(
            AgentApprovalDecision(approval_id=approval.pk, decision="approved")
        )
        await self.controller.run_attempt(
            run.pk, execution_mode="inline", executor_id="test"
        )
        await database_sync_to_async(self.assert_completed)(run.pk)

    def prepare_sse(self) -> None:
        """Reset effects and use SSE for the next independently audited conversation."""
        self.server.effects.clear()
        self.server.sse = True

    def get_test_scenarios(self) -> list[ChannelScenario]:
        """Declare real controller approval flows over both supported response transports."""
        return [
            ChannelScenario(
                name="External JSON calls pause and resume through the controller",
                steps=[
                    ChannelAction(
                        name="Discover, approve and dispatch",
                        execute=self.approval_flow,
                    )
                ],
            ),
            ChannelScenario(
                name="External SSE calls preserve durable results",
                prepare=self.prepare_sse,
                steps=[
                    ChannelAction(
                        name="Discover, approve and dispatch",
                        execute=self.approval_flow,
                    )
                ],
            ),
        ]

    def test_dynamic_discovery_namespaces_colliding_internal_and_external_names(
        self,
    ) -> None:
        """Keep identical remote names distinct across integrations and from internal names."""
        self.agent.internal_tool_mode = "all"
        self.agent.save()
        registry = BloomerpRouteRegistry()
        registry.register(
            name="Internal effect",
            url_name="fixture_effect",
            route_type="mcp",
            mcp=McpTool(input_schema={"type": "object"}, read_only_hint=True),
        )(fixture_internal_tool)
        self.enterContext(
            patch.object(
                router,
                "get_mcp_routes",
                return_value=[*router.get_mcp_routes(), *registry.routes],
            )
        )
        second = MCPIntegration.objects.create(
            name="Second", endpoint_url="https://second.example.com/mcp"
        )
        self.agent.mcp_integrations.add(second)
        definitions = self.client.definitions()
        names = {item.identifier for item in definitions}
        self.assertIn("fixture_effect", names)
        self.assertIn(external_tool_name(self.integration.pk, "fixture_effect"), names)
        self.assertIn(external_tool_name(second.pk, "fixture_effect"), names)
        self.assertEqual(len(names), len(definitions))
        self.assertTrue(
            all(len(name) <= 64 for name in names if name.startswith("external_"))
        )
        self.server.tools.append({**self.server.tools[0], "name": "newly_registered"})
        self.assertIn(
            external_tool_name(self.integration.pk, "newly_registered"),
            {item.identifier for item in self.client.definitions()},
        )

    def test_reserved_namespace_collision_is_refused(self) -> None:
        """Fail closed if an internal registration occupies a remote tool identity."""
        registry = BloomerpRouteRegistry()
        registry.register(
            name="Conflicting internal tool",
            url_name=external_tool_name(self.integration.pk, "fixture_effect"),
            route_type="mcp",
            mcp=McpTool(input_schema={"type": "object"}),
        )(fixture_internal_tool)
        with (
            patch.object(router, "get_mcp_routes", return_value=registry.routes),
            self.assertRaisesMessage(MCPUnavailableError, "identifiers conflict"),
        ):
            self.client.definitions()
        self.assertEqual(self.server.effects, [])

    def test_shared_personal_and_noauth_resolution(self) -> None:
        """Resolve only the actor's personal account and never borrow another user's connection."""
        self.client.definitions()
        self.assertEqual(
            self.server.requests[0].headers["Authorization"],
            "Bearer remote-shared-secret",
        )
        self.connection.delete()
        self.integration.connection_mode = "personal"
        self.integration.save()
        other = MCPConnection(
            integration=self.integration, user=self.other, status="ready"
        )
        other.set_credentials({"api_key": "other-user-secret"})
        other.save()
        with self.assertRaisesMessage(MCPUnavailableError, "personal connection"):
            self.client.definitions()
        own = MCPConnection(
            integration=self.integration, user=self.user, status="ready"
        )
        own.set_credentials({"api_key": "own-user-secret"})
        own.save()
        self.server.requests.clear()
        self.client.definitions()
        self.assertEqual(
            self.server.requests[0].headers["Authorization"], "Bearer own-user-secret"
        )
        own.delete()
        other.delete()
        self.integration.authentication_type = "none"
        self.integration.save()
        self.server.requests.clear()
        self.client.definitions()
        self.assertNotIn("Authorization", self.server.requests[0].headers)

    def test_expired_revoked_and_disabled_connections_are_unavailable(self) -> None:
        """Refuse inactive connections, expiry and integration disablement before discovery."""
        for status in ("pending", "expired", "revoked", "error"):
            with self.subTest(status=status):
                self.connection.status = status
                self.connection.save()
                with self.assertRaisesMessage(MCPUnavailableError, "Reconnect"):
                    self.client.definitions()
        self.connection.status = "ready"
        self.connection.expires_at = timezone.now() - timedelta(seconds=1)
        self.connection.save()
        with self.assertRaisesMessage(MCPUnavailableError, "expired"):
            self.client.definitions()
        self.integration.enabled = False
        self.integration.save()
        with self.assertRaisesMessage(MCPUnavailableError, "disabled"):
            self.client.definitions()
        self.assertEqual(self.server.requests, [])

    def test_selected_and_enabled_state_is_rechecked_at_dispatch(self) -> None:
        """Refuse crafted or stale calls after removal and after integration disablement."""
        run, coordinator, proposal = self.run_coordinator()
        self.agent.mcp_integrations.clear()
        with self.assertRaisesMessage(PermissionDenied, "no longer selected"):
            coordinator.execute(proposal)
        self.agent.mcp_integrations.add(self.integration)
        self.integration.enabled = False
        self.integration.save()
        with self.assertRaisesMessage(MCPUnavailableError, "disabled"):
            coordinator.execute(proposal)
        self.assertFalse(run.tool_calls.exists())
        self.assertEqual(self.server.effects, [])

    def test_changed_contract_and_invalid_arguments_never_dispatch(self) -> None:
        """Compare fresh schemas with the pinned contract and validate arguments before effects."""
        run, coordinator, proposal = self.run_coordinator()
        invalid = proposal.model_copy(update={"arguments": {"value": "bad"}})
        with self.assertRaises(JsonSchemaValidationError):
            coordinator.execute(invalid)
        self.server.tools[0]["description"] = "Changed contract"
        with self.assertRaisesMessage(ValidationError, "contract changed"):
            coordinator.execute(proposal)
        self.assertFalse(run.tool_calls.exists())
        self.assertEqual(self.server.effects, [])

    def test_agent_grant_revoked_during_catalog_prevents_external_effect(self) -> None:
        """Recheck agent use after remote catalog I/O and immediately before tools/call."""
        from bloomerp.models.agents import AIAgentAccess

        self.agent.created_by = self.other
        self.agent.save()
        grant = AIAgentAccess.objects.create(
            name="Temporary agent audience",
            model=self.agent,
            all_authenticated_users=True,
        )
        _, _, proposal = self.run_coordinator()
        handle = self.server.handle

        def revoke_after_catalog(request: httpx.Request) -> httpx.Response:
            """Revoke the grant after answering tools/list, before the effect request."""
            response = handle(request)
            if (
                request.method == "POST"
                and json.loads(request.content).get("method") == "tools/list"
            ):
                grant.all_authenticated_users = False
                grant.save(update_fields=["all_authenticated_users"])
            return response

        with (
            patch.object(self.server, "handle", side_effect=revoke_after_catalog),
            self.assertRaises(PermissionDenied),
        ):
            self.client.dispatch(proposal)
        self.assertEqual(self.server.effects, [])

    def test_stale_approval_refuses_rotated_credentials(self) -> None:
        """Prevent an approved proposal from running against a different account revision."""
        run = self.new_run()
        self.execute(run)
        approval = AIApproval.objects.get(tool_call__run=run)
        async_to_sync(self.controller.decide_approval)(
            AgentApprovalDecision(approval_id=approval.pk, decision="approved")
        )
        self.connection.set_credentials({"api_key": "rotated-secret"})
        self.connection.save()
        self.execute(run)
        self.assertEqual(run.status, "failed")
        self.assertEqual(self.server.effects, [])

    def test_uncertain_effect_is_persisted_and_never_replayed(self) -> None:
        """Record lost remote results as unknown and reconcile duplicates without another call."""
        run, coordinator, proposal = self.run_coordinator()
        self.server.lose_result = True
        with self.assertRaises(MCPUnavailableError):
            coordinator.execute(proposal)
        self.assertEqual(run.tool_calls.get().status, "unknown")
        self.server.lose_result = False
        outcome = coordinator.execute(proposal)
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.error.code, "tool_outcome_unknown")
        self.assertEqual(len(self.server.effects), 1)

    def test_remote_iserror_result_is_preserved(self) -> None:
        """Persist a returned tool error without treating it as lost delivery or replaying it."""
        run, coordinator, proposal = self.run_coordinator()
        self.server.result = {
            "content": [{"type": "text", "text": "Remote permission denied"}],
            "isError": True,
        }
        outcome = coordinator.execute(proposal)
        self.assertEqual(outcome.result, self.server.result)
        self.assertEqual(run.tool_calls.get().status, "failed")
        coordinator.execute(proposal)
        self.assertEqual(len(self.server.effects), 1)

    def test_readonly_tools_execute_without_approval_and_redact_reflected_secrets(
        self,
    ) -> None:
        """Keep credentials out of definitions, model results and persisted remote output."""
        self.server.tools[0]["annotations"] = {"readOnlyHint": True}
        self.server.tools[0]["description"] = "Reflected remote-shared-secret"
        self.server.result["content"][0]["text"] = "Reflected remote-shared-secret"
        definitions = self.client.definitions()
        self.assertNotIn(
            "remote-shared-secret",
            json.dumps([item.model_dump(mode="json") for item in definitions]),
        )
        run = self.new_run()
        self.execute(run)
        self.assertEqual(run.status, "completed", run.error)
        self.assertFalse(AIApproval.objects.filter(tool_call__run=run).exists())
        self.assertNotIn(
            "remote-shared-secret", json.dumps(run.tool_calls.get().result)
        )
        self.assertIn("[redacted]", json.dumps(run.tool_calls.get().result))

    def test_unavailable_server_gives_safe_actionable_controller_error(self) -> None:
        """Show a useful connection error while keeping raw server and transport secrets out."""
        self.server.status = 401
        run = self.new_run()
        self.execute(run)
        self.assertEqual(run.status, "failed")
        self.assertIn("Reconnect", run.error["message"])
        self.assertEqual(self.server.effects, [])

    def test_missing_selection_and_inactive_actor_are_denied(self) -> None:
        """Never resolve a connection for an unselected integration or inactive user."""
        self.agent.mcp_integrations.clear()
        with self.assertRaises(PermissionDenied):
            resolve_remote_binding(self.agent.pk, self.user.pk, self.integration.pk)
        self.agent.mcp_integrations.add(self.integration)
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(PermissionDenied):
            resolve_remote_binding(self.agent.pk, self.user.pk, self.integration.pk)

    def test_coordinator_refuses_another_actors_client(self) -> None:
        """Never dispatch using a different actor even when the caller crafts a composite client."""
        run, coordinator, proposal = self.run_coordinator()
        coordinator.client = AgentMcpClient(
            self.other.pk, "https://erp.test", str(self.agent.pk)
        )
        with self.assertRaisesMessage(PermissionDenied, "another actor"):
            coordinator.execute(proposal)
        self.assertFalse(run.tool_calls.exists())
        self.assertEqual(self.server.effects, [])

    def test_oauth_expiry_requires_reconnect_without_refresh_or_dispatch(self) -> None:
        """Use encrypted valid bearer credentials and explicitly reject expired OAuth accounts."""
        self.connection.delete()
        self.integration.authentication_type = "oauth"
        self.integration.save()
        connection = MCPConnection(
            integration=self.integration,
            status="ready",
            expires_at=timezone.now() + timedelta(hours=1),
        )
        connection.set_credentials(
            {
                "access_token": "oauth-token-secret",
                "refresh_token": "oauth-refresh-secret",
            }
        )
        connection.save()
        self.client.definitions()
        self.assertEqual(
            self.server.requests[0].headers["Authorization"],
            "Bearer oauth-token-secret",
        )
        self.server.requests.clear()
        connection.expires_at = timezone.now() - timedelta(seconds=1)
        connection.save()
        with self.assertRaisesMessage(MCPUnavailableError, "Reconnect"):
            self.client.definitions()
        self.assertEqual(self.server.requests, [])

    def test_invalid_output_is_uncertain(self) -> None:
        """Validate structured output before claiming successful execution of a remote effect."""
        self.server.tools[0]["outputSchema"] = {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        }
        run, coordinator, proposal = self.run_coordinator()
        self.server.result["structuredContent"] = {"value": "invalid"}
        with self.assertRaisesMessage(MCPUnavailableError, "output schema"):
            coordinator.execute(proposal)
        self.assertEqual(run.tool_calls.get().status, "unknown")
        self.assertEqual(len(self.server.effects), 1)

    def test_remote_schema_refs_do_not_fetch(self) -> None:
        """Reject remote schema references at discovery without requesting their destinations."""
        self.server.tools[0]["inputSchema"]["properties"]["value"] = {
            "$ref": "https://private.example.com/schema"
        }
        with self.assertRaisesMessage(MCPUnavailableError, "local definitions"):
            self.client.definitions()
        self.assertTrue(
            all(
                str(request.url) == self.integration.endpoint_url
                for request in self.server.requests
            )
        )
        self.assertEqual(self.server.effects, [])

    def test_stale_approval_refuses_removed_or_disabled_integration(self) -> None:
        """Reload selection on resume so an old approval cannot revive an integration."""
        run = self.new_run()
        self.execute(run)
        approval = AIApproval.objects.get(tool_call__run=run)
        async_to_sync(self.controller.decide_approval)(
            AgentApprovalDecision(approval_id=approval.pk, decision="approved")
        )
        self.agent.mcp_integrations.clear()
        self.execute(run)
        self.assertEqual(run.status, "failed")
        self.assertEqual(self.server.effects, [])
