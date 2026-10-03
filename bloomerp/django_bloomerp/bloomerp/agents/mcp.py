"""Execute the existing MCP protocol locally without changing its public contracts."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from pydantic import BaseModel, ConfigDict, Field
from rest_framework.test import APIRequestFactory, force_authenticate

from bloomerp.agents.runtime import (
    AgentRuntimeToolDefinition,
    AgentRuntimeToolOutcome,
    AgentRuntimeToolProposal,
)
from bloomerp.mcp.view import McpEndpointView

if TYPE_CHECKING:
    from bloomerp.models.agents import AIRun, AIRunAttempt


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

    def __init__(self, user_id: int | str, origin: str) -> None:
        """Bind identity and instance origin without retaining HTTP credentials."""
        self.user_id = user_id
        self.origin = origin

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Decode the rendered MCP wire response, matching external JSON clients."""
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
        return {item["name"]: item for item in self.request("tools/list")["tools"]}

    def definitions(self) -> tuple[AgentRuntimeToolDefinition, ...]:
        """Translate field spelling only, retaining MCP names, schemas and annotations."""
        return tuple(self.definition(item) for item in self.catalog().values())

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


class McpToolCoordinator:
    """Persist proposals and approvals before invoking the same MCP execution path."""

    def __init__(
        self, run: AIRun, attempt: AIRunAttempt, client: LocalMcpClient
    ) -> None:
        """Bind every operation to the run's actor and current fenced executor."""
        self.run = run
        self.attempt = attempt
        self.client = client
        self.rules = AgentApprovalRules.model_validate(
            run.config_snapshot.get("approval_rules", {})
        )

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

        catalog = self.client.catalog()
        definition = catalog.get(proposal.tool_identifier)
        if (
            definition is None
            or self.client.definition(definition).version != proposal.tool_version
        ):
            raise ValidationError("MCP tool contract changed or is unavailable")
        Draft202012Validator(definition["inputSchema"]).validate(proposal.arguments)
        tool, dispatch = AIToolCall.prepare(
            self.run,
            self.attempt.lease_token,
            proposal,
            requires_approval=self.rules.requires_approval(definition),
        )
        if dispatch:
            try:
                result = self.client.request(
                    "tools/call",
                    {
                        "name": proposal.tool_identifier,
                        "arguments": proposal.arguments,
                    },
                )
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
