"""Resolve selected integrations and private actor connections for audited MCP dispatch."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from bloomerp.models.agents import AIAgent, MCPConnection, MCPIntegration
from bloomerp.services.mcp.client import MCPUnavailableError, RemoteMcpSession

EXTERNAL_NAME = re.compile(r"^external_([0-9a-f]{32})_([0-9a-f]{20})$")


def external_tool_name(integration_id: UUID, remote_name: str) -> str:
    """Keep provider-safe names stable and distinct across integration identities."""
    digest = hashlib.sha256(remote_name.encode()).hexdigest()[:20]
    return f"external_{integration_id.hex}_{digest}"


def external_integration_id(name: str) -> UUID | None:
    """Recognize the reserved external namespace without trusting a model-supplied endpoint."""
    match = EXTERNAL_NAME.fullmatch(name)
    return UUID(hex=match[1]) if match else None


def redact_secrets(value: Any, secrets: tuple[str, ...]) -> Any:
    """Remove reflected stored credentials from remote contracts and results before persistence."""
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [redact_secrets(item, secrets) for item in value]
    if isinstance(value, dict):
        return {
            redact_secrets(key, secrets): redact_secrets(item, secrets)
            for key, item in value.items()
        }
    return value


def ensure_local_schema_refs(schema: Any) -> None:
    """Reject references that could fetch remote resources while validating a tool contract."""
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(value, str) or not value.startswith("#")
            ):
                raise MCPUnavailableError(
                    "External MCP schemas may reference only local definitions."
                )
            ensure_local_schema_refs(value)
    elif isinstance(schema, list):
        for value in schema:
            ensure_local_schema_refs(value)


@dataclass(frozen=True)
class RemoteBinding:
    """Carry a safe configuration revision and transport-only private credentials."""

    integration_id: UUID
    label: str
    endpoint: str
    revision: str
    authorization: str | None = field(default=None, repr=False)
    secrets: tuple[str, ...] = field(default=(), repr=False)

    def session(self, *, deadline: float | None = None) -> RemoteMcpSession:
        """Create one bounded session without retaining credentials in the agent runtime."""
        return RemoteMcpSession(self.endpoint, self.authorization, deadline=deadline)

    def catalog(self, session: RemoteMcpSession) -> dict[str, dict[str, Any]]:
        """Validate and namespace remote contracts while pinning integration and connection revisions."""
        tools = {}
        for remote in session.catalog():
            clean = redact_secrets(remote, self.secrets)
            try:
                Draft202012Validator.check_schema(clean["inputSchema"])
                ensure_local_schema_refs(clean["inputSchema"])
                if clean["inputSchema"].get("type") != "object":
                    raise ValueError("Tool input must be an object")
                if "outputSchema" in clean:
                    Draft202012Validator.check_schema(clean["outputSchema"])
                    ensure_local_schema_refs(clean["outputSchema"])
                    if not isinstance(clean["outputSchema"], dict):
                        raise ValueError("Output schema must be an object")
                if not isinstance(clean.get("description", ""), str) or not isinstance(
                    clean.get("title", ""), str
                ):
                    raise TypeError("Invalid description or title")
                if not isinstance(clean.get("annotations", {}), dict):
                    raise TypeError("Invalid annotations")
            except (SchemaError, ValueError, TypeError):
                raise MCPUnavailableError(
                    "The integration advertised an invalid MCP tool schema or metadata."
                ) from None
            name = external_tool_name(self.integration_id, remote["name"])
            if name in tools:
                raise MCPUnavailableError(
                    "The integration advertised colliding MCP tool identifiers."
                )
            tools[name] = {
                "name": name,
                "title": f"{self.label}: {clean.get('title') or clean['name']}",
                "description": clean.get("description", ""),
                "inputSchema": clean["inputSchema"],
                "annotations": clean.get("annotations", {}),
                "_bloomerp_binding": {
                    "integration_id": str(self.integration_id),
                    "revision": self.revision,
                },
            }
            session.remote_tool_names[name] = remote["name"]
            if "outputSchema" in clean:
                tools[name]["outputSchema"] = clean["outputSchema"]
        return tools


def resolve_remote_binding(
    agent_id: str | UUID | None, user_id: int | str | UUID, integration_id: UUID
) -> RemoteBinding:
    """Reload selection and resolve only the single shared or exact acting user's ready account."""
    if not get_user_model().objects.filter(pk=user_id, is_active=True).exists():
        raise PermissionDenied("Agent access denied")
    if agent_id is None:
        raise PermissionDenied("External MCP tools require an agent configuration")
    try:
        agent = AIAgent.objects.get(pk=agent_id)
        integration = agent.mcp_integrations.get(pk=integration_id)
    except (
        AIAgent.DoesNotExist,
        MCPIntegration.DoesNotExist,
        ValidationError,
        ValueError,
    ):
        raise PermissionDenied(
            "External MCP integration is no longer selected for this agent"
        ) from None
    label = integration.name[:100]
    if not integration.enabled:
        raise MCPUnavailableError(
            f"External MCP integration '{label}' is disabled. Reconfigure the agent or enable the integration."
        )
    connection = None
    authorization = None
    secrets: tuple[str, ...] = ()
    if integration.authentication_type != MCPIntegration.AuthenticationType.NONE:
        owner_id = (
            user_id
            if integration.connection_mode == MCPIntegration.ConnectionMode.PERSONAL
            else None
        )
        connection = MCPConnection.objects.filter(
            integration=integration, user_id=owner_id
        ).first()
        if connection is None:
            scope = "your personal" if owner_id is not None else "its shared"
            raise MCPUnavailableError(
                f"External MCP integration '{label}' needs {scope} connection. Connect or reconnect before using its tools."
            )
        if connection.status != MCPConnection.Status.READY or (
            connection.expires_at is not None
            and connection.expires_at <= timezone.now()
        ):
            raise MCPUnavailableError(
                f"External MCP integration '{label}' has an unavailable or expired connection. Reconnect before using its tools."
            )
        try:
            credentials = connection.validated_credentials()
        except ValidationError:
            raise MCPUnavailableError(
                f"External MCP integration '{label}' credentials are unavailable. Reconnect before using its tools."
            ) from None
        secret_values = [
            value.get_secret_value()
            for value in credentials.__dict__.values()
            if hasattr(value, "get_secret_value")
        ]
        secrets = tuple(value for value in secret_values if value)
        bearer = getattr(credentials, "api_key", None) or getattr(
            credentials, "access_token", None
        )
        authorization = "Bearer " + bearer.get_secret_value()
    configuration = {
        "integration_id": str(integration.pk),
        "endpoint": integration.endpoint_url,
        "name": integration.name,
        "mode": integration.connection_mode,
        "auth": integration.authentication_type,
        "client_id": integration.oauth_client_id,
        "scopes": integration.oauth_scopes,
        "connection_id": str(connection.pk) if connection else None,
        "connection_owner": str(connection.user_id) if connection else None,
        "credentials": connection.credentials_encrypted if connection else None,
        "expires_at": connection.expires_at.isoformat()
        if connection and connection.expires_at
        else None,
    }
    revision = hashlib.sha256(
        json.dumps(configuration, sort_keys=True).encode()
    ).hexdigest()
    return RemoteBinding(
        integration.pk,
        redact_secrets(label, secrets),
        integration.endpoint_url,
        revision,
        authorization,
        secrets,
    )
