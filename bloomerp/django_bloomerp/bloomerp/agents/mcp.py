"""Execute the existing MCP protocol locally without changing its public contracts."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from pydantic import BaseModel, ConfigDict, Field
from rest_framework.test import APIRequestFactory, force_authenticate

from bloomerp.agents.resource_access import (
    RESOURCE_TOOL_PREFIX,
    require_resource_uri,
    resource_tool_catalog,
    resource_tool_uri,
)
from bloomerp.agents.runtime import (
    AgentRuntimeToolDefinition,
    AgentRuntimeToolOutcome,
    AgentRuntimeToolProposal,
    AgentRuntimeToolStartedEvent,
)
from bloomerp.agents.tool_access import allowed_internal_tools, require_internal_tool
from bloomerp.mcp.view import McpEndpointView

if TYPE_CHECKING:
    from bloomerp.models.agents import AIRun, AIRunAttempt, AIRunEvent, AIToolCall


class AgentApprovalRules(BaseModel):
    """Gate effects separately from permissions; unknown tools require approval by default."""

    model_config = ConfigDict(extra="forbid")
    default: Literal["writes", "always", "never"] = "writes"
    tools: dict[str, Literal["always", "never"]] = Field(default_factory=dict)

    def requires_approval(self, definition: dict[str, Any]) -> bool:
        """Apply exact-name overrides or the MCP read-only annotation."""
        mode = self.tools.get(definition["name"], self.default)
        return mode == "always" or (
            mode == "writes"
            and definition.get("annotations", {}).get("readOnlyHint") is not True
        )


class LocalMcpClient:
    """Re-enter the HTTP MCP view as a freshly loaded server-authenticated actor."""

    def __init__(
        self, user_id: int | str, origin: str, agent_id: str | UUID | None = None
    ) -> None:
        """Bind identity and instance origin without retaining HTTP credentials."""
        self.user_id = user_id
        self.origin = origin
        self.agent_id = agent_id

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Decode the rendered MCP wire response, matching external JSON clients."""
        if method == "tools/call":
            require_internal_tool(self.agent_id, (params or {}).get("name"))
        if method == "resources/read":
            require_resource_uri(self.agent_id, (params or {}).get("uri"))
        user = get_user_model().objects.filter(pk=self.user_id, is_active=True).first()
        if user is None:
            raise PermissionDenied("Agent access denied")
        origin = urlsplit(self.origin)
        request = APIRequestFactory().post(
            "/mcp/",
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            format="json",
            HTTP_HOST=origin.netloc,
            secure=origin.scheme == "https",
            HTTP_ACCEPT="application/json, text/event-stream",
            HTTP_MCP_PROTOCOL_VERSION="2025-11-25",
        )
        force_authenticate(request, user=user)
        response = McpEndpointView.as_view()(request)
        if response.status_code >= 400:
            raise ValidationError("MCP request failed")
        response.render()
        envelope = json.loads(response.content)
        if "error" in envelope:
            raise ValidationError("MCP request failed")
        return envelope["result"]

    def catalog(self) -> dict[str, dict[str, Any]]:
        """Read the same catalog exposed to external MCP clients."""
        allowed = allowed_internal_tools(self.agent_id)
        registered = self.request("tools/list")["tools"]
        if any(item["name"].startswith(RESOURCE_TOOL_PREFIX) for item in registered):
            raise ValidationError(
                "MCP tool identifiers use the reserved resource prefix"
            )
        tools = {
            item["name"]: item
            for item in registered
            if allowed is None or item["name"] in allowed
        }

        resources = resource_tool_catalog(self.agent_id)
        if tools.keys() & resources.keys():
            raise ValidationError(
                "MCP resource tool identifiers conflict with registered tools"
            )
        return {**tools, **resources}

    def definitions(self) -> tuple[AgentRuntimeToolDefinition, ...]:
        """Translate field spelling only, retaining MCP names, schemas and annotations."""
        return tuple(self.definition(item) for item in self.catalog().values())

    def check_tool_access(self, agent_id: str | UUID | None, name: str) -> None:
        """Check the run's current agent independently of a client's catalog filtering."""
        if name.startswith(RESOURCE_TOOL_PREFIX):
            if name not in resource_tool_catalog(agent_id):
                raise PermissionDenied(
                    "Internal MCP resource is not allowed for this agent"
                )
        else:
            require_internal_tool(agent_id, name)

    def dispatch(self, proposal: AgentRuntimeToolProposal) -> dict[str, Any]:
        """Invoke the local protocol only after the coordinator owns persisted dispatch."""
        if proposal.tool_identifier.startswith(RESOURCE_TOOL_PREFIX):
            uri = resource_tool_uri(
                self.agent_id, proposal.tool_identifier, proposal.arguments
            )
            result = self.request("resources/read", {"uri": uri})
            return {
                "content": [
                    {"type": "resource", "resource": entry}
                    for entry in result["contents"]
                ]
            }
        return self.request(
            "tools/call",
            {"name": proposal.tool_identifier, "arguments": proposal.arguments},
        )

    @staticmethod
    def definition(item: dict[str, Any]) -> AgentRuntimeToolDefinition:
        """Fingerprint the complete advertised contract so changed tools need fresh approval."""
        version = hashlib.sha256(
            json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return AgentRuntimeToolDefinition(
            identifier=item["name"],
            version=version,
            description=item.get("description", ""),
            input_schema=item["inputSchema"],
            output_schema=item.get("outputSchema"),
            title=item.get("title"),
            annotations=item.get("annotations", {}),
        )


class AgentMcpClient(LocalMcpClient):
    """Combine allowed internal tools with selected external integrations for one actor."""

    def check_tool_access(self, agent_id: str | UUID | None, name: str) -> None:
        """Revalidate agent selection and account ownership for reserved external identifiers."""
        from bloomerp.agents.external_mcp import (
            external_integration_id,
            resolve_remote_binding,
        )

        integration_id = external_integration_id(name)
        if integration_id is None:
            super().check_tool_access(agent_id, name)
        else:
            if str(agent_id) != str(self.agent_id):
                raise PermissionDenied("External MCP client belongs to another agent")
            resolve_remote_binding(agent_id, self.user_id, integration_id)

    def catalog(self) -> dict[str, dict[str, Any]]:
        """Discover selected integrations afresh; unavailable accounts produce actionable failures."""
        from bloomerp.agents.external_mcp import resolve_remote_binding
        from bloomerp.models.agents import AIAgent
        from bloomerp.services.mcp.client import (
            MAX_RESPONSE_BYTES,
            MAX_SESSION_SECONDS,
            MAX_TOOLS,
            MCPUnavailableError,
        )

        tools = super().catalog()
        if self.agent_id is None:
            return tools
        agent = AIAgent.objects.get(pk=self.agent_id)
        # Reserve against the complete internal registry, including disallowed tools.
        internal_names = {
            item["name"] for item in super().request("tools/list")["tools"]
        } | resource_tool_catalog(None).keys()
        integration_ids = list(
            agent.mcp_integrations.order_by("pk").values_list("pk", flat=True)[:21]
        )
        if len(integration_ids) > 20:
            raise MCPUnavailableError(
                "Select at most 20 external MCP integrations per agent."
            )
        deadline = time.monotonic() + MAX_SESSION_SECONDS
        for integration_id in integration_ids:
            binding = resolve_remote_binding(
                self.agent_id, self.user_id, integration_id
            )
            try:
                with binding.session(deadline=deadline) as session:
                    remote_tools = binding.catalog(session)
            except MCPUnavailableError as error:
                raise MCPUnavailableError(
                    f"External MCP integration '{binding.label}': {error}"
                ) from None
            if (
                internal_names.intersection(remote_tools)
                or tools.keys() & remote_tools.keys()
            ):
                raise MCPUnavailableError(
                    "External MCP tool identifiers conflict with registered tools. Reconfigure the integration."
                )
            tools.update(remote_tools)
            if (
                len(tools) > MAX_TOOLS
                or len(json.dumps(tools).encode()) > MAX_RESPONSE_BYTES
            ):
                raise MCPUnavailableError(
                    "The combined MCP catalog exceeds its tool or size limit. Select fewer integrations."
                )
        return tools

    def dispatch(self, proposal: AgentRuntimeToolProposal) -> dict[str, Any]:
        """Recheck the exact remote contract and binding in the session that will execute it."""
        from bloomerp.agents.external_mcp import (
            external_integration_id,
            redact_secrets,
            resolve_remote_binding,
        )
        from bloomerp.services.mcp.client import MCPUnavailableError

        integration_id = external_integration_id(proposal.tool_identifier)
        if integration_id is None:
            return super().dispatch(proposal)
        binding = resolve_remote_binding(self.agent_id, self.user_id, integration_id)
        with binding.session() as session:
            definition = binding.catalog(session).get(proposal.tool_identifier)
            if (
                definition is None
                or self.definition(definition).version != proposal.tool_version
            ):
                raise ValidationError(
                    "External MCP tool contract or connection changed"
                )
            current = resolve_remote_binding(
                self.agent_id, self.user_id, integration_id
            )
            if current.revision != binding.revision:
                raise ValidationError("External MCP connection changed before dispatch")
            result = session.request(
                "tools/call",
                {
                    "name": session.remote_tool_names[proposal.tool_identifier],
                    "arguments": proposal.arguments,
                },
            )
            if not isinstance(result.get("content"), list) or (
                "isError" in result and not isinstance(result["isError"], bool)
            ):
                raise MCPUnavailableError(
                    "The external MCP server returned an invalid tool result; its outcome may be uncertain."
                )
            if any(
                not isinstance(block, dict) or not isinstance(block.get("type"), str)
                for block in result["content"]
            ):
                raise MCPUnavailableError(
                    "The external MCP server returned invalid content; its outcome may be uncertain."
                )
            if "outputSchema" in definition and not result.get("isError"):
                from jsonschema import Draft202012Validator
                from jsonschema.exceptions import (
                    ValidationError as JsonSchemaValidationError,
                )
                from referencing import Registry

                try:
                    Draft202012Validator(
                        definition["outputSchema"], registry=Registry()
                    ).validate(result.get("structuredContent"))
                except JsonSchemaValidationError:
                    raise MCPUnavailableError(
                        "The external MCP result did not match its output schema; its outcome may be uncertain."
                    ) from None
            return redact_secrets(result, binding.secrets)


class McpToolCoordinator:
    """Persist proposals and approvals before invoking the same MCP execution path."""

    def __init__(
        self,
        run: AIRun,
        attempt: AIRunAttempt,
        client: LocalMcpClient,
        publish: Callable[[AIRunEvent], None] | None = None,
    ) -> None:
        """Bind every operation to the run's actor and current fenced executor."""
        self.run = run
        self.attempt = attempt
        self.client = client
        self.publish = publish

    def report_tool_started(self, tool: AIToolCall) -> None:
        """Commit a fenced progress event after approval, without publishing arguments or results."""
        event = self.run.apply_runtime_event(
            AgentRuntimeToolStartedEvent(
                run_id=self.run.pk, attempt_id=self.attempt.pk, tool_call_id=tool.pk
            ),
            lease_token=self.attempt.lease_token,
        )
        if self.publish is not None:
            try:
                self.publish(event)
            except Exception:  # noqa: BLE001 - live delivery must not prevent an authorized effect
                # The committed event remains available through replay if live delivery fails.
                logging.getLogger(__name__).warning("Tool progress delivery failed")

    async def call(self, proposal: AgentRuntimeToolProposal) -> AgentRuntimeToolOutcome:
        """Persist or reconcile a provider proposal without duplicating effects."""
        return await database_sync_to_async(self.execute, thread_sensitive=False)(
            proposal
        )

    async def resolve(self, tool_call_id: UUID) -> AgentRuntimeToolOutcome:
        """Resolve only an exact persisted proposal belonging to this run."""
        proposal = await database_sync_to_async(self.load_proposal)(tool_call_id)
        return await self.call(proposal)

    def load_proposal(self, tool_call_id: UUID) -> AgentRuntimeToolProposal:
        """Prevent continuation IDs from crossing run boundaries."""
        tool = self.run.tool_calls.get(pk=tool_call_id)
        return AgentRuntimeToolProposal(
            provider_call_id=tool.provider_call_id,
            tool_identifier=tool.tool_identifier,
            tool_version=tool.tool_version,
            arguments=tool.arguments,
        )

    def execute(self, proposal: AgentRuntimeToolProposal) -> AgentRuntimeToolOutcome:
        """Revalidate the current contract and permissions; never retry uncertain effects."""
        from jsonschema import Draft202012Validator

        from bloomerp.models.agents import AIToolCall

        if str(self.client.user_id) != str(self.run.initiated_by_id):
            raise PermissionDenied("MCP client belongs to another actor")
        agent_id = self.run.config_snapshot.get("model_record_id")
        self.client.check_tool_access(agent_id, proposal.tool_identifier)
        catalog = self.client.catalog()
        definition = catalog.get(proposal.tool_identifier)
        if (
            definition is None
            or self.client.definition(definition).version != proposal.tool_version
        ):
            raise ValidationError("MCP tool contract changed or is unavailable")
        from referencing import Registry

        Draft202012Validator(definition["inputSchema"], registry=Registry()).validate(
            proposal.arguments
        )
        from bloomerp.models.agents import AIConversation

        rules = AgentApprovalRules.model_validate(
            AIConversation.objects.get(pk=self.run.conversation_id).approval_rules
        )
        tool, dispatch = AIToolCall.prepare(
            self.run,
            self.attempt.lease_token,
            proposal,
            requires_approval=rules.requires_approval(definition),
            tool_title=definition.get("title") or "",
        )
        if dispatch:
            self.client.check_tool_access(agent_id, proposal.tool_identifier)
            try:
                self.report_tool_started(tool)
                result = self.client.dispatch(proposal)
            except (
                Exception
            ):  # A lost result must never cause a mutation to be replayed.
                tool.mark_unknown(self.attempt.lease_token)
                raise
            tool.complete(result, self.attempt.lease_token)
        if tool.status == "completed":
            from django.http import HttpRequest

            from bloomerp.models.agents import AIArtifact

            request = HttpRequest()
            request.user = get_user_model().objects.get(
                pk=self.run.initiated_by_id, is_active=True
            )
            try:
                AIArtifact.from_tool_result(tool, request, self.attempt.lease_token)
            except Exception:
                # A presentation failure must never retry or hide a successful mutation.
                logging.getLogger(__name__).exception(
                    "Artifact adaptation failed for tool call %s", tool.pk
                )
        return tool.runtime_outcome()
