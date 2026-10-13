"""Proposed mcp artifact payload and registration, without I/O or execution wiring."""

from pydantic import Field

from bloomerp.agents.definition import (
    AIArtifactDescription,
    AIArtifactPayload,
    AIArtifactTypeDefinition,
)


class McpArtifactPayload(AIArtifactPayload):
    """Identify a mcp source without copying its live content or permissions."""

    server_key: str = Field(default="local", min_length=1, max_length=255)
    resource_uri: str = Field(min_length=1, max_length=2048)


def describe_mcp(payload: McpArtifactPayload) -> AIArtifactDescription:
    """Describe the reference without fetching content or asserting target access."""
    return AIArtifactDescription(
        title=payload.resource_uri,
        summary=f"MCP resource reference on configured server {payload.server_key}; access must be checked when read.",
    )


MCP_ARTIFACT = AIArtifactTypeDefinition[McpArtifactPayload](
    key="mcp",
    label="MCP resource",
    model=McpArtifactPayload,
    describe=describe_mcp,
    icon="fa-link",
)
