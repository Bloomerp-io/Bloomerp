"""Expose selected MCP resources as read-only tools for tool-calling models."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import quote
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from jsonschema import Draft202012Validator
from referencing import Registry

from bloomerp.mcp.definition import (
    RESOURCE_VARIABLE_PATTERN,
    McpResource,
    McpResourceTemplate,
)
from bloomerp.mcp.view import McpEndpointView
from bloomerp.router import BloomerpRoute, router

RESOURCE_TOOL_PREFIX = "bloomerp_resource_"


def resource_identity(route: BloomerpRoute) -> str:
    """Use the public URI or URI template as the stable configuration identity."""
    contract = route.mcp
    assert isinstance(contract, (McpResource, McpResourceTemplate))
    return contract.uri if isinstance(contract, McpResource) else contract.uri_template


def resource_routes() -> list[BloomerpRoute]:
    """Discover concrete and parameterized readers without loading their contents."""
    return [*router.get_mcp_resources(), *router.get_mcp_resource_templates()]


def internal_resource_choices() -> list[tuple[str, str]]:
    """Show registered resource titles alongside their stable public identities."""
    return sorted(
        [
            (
                resource_identity(route),
                f"{route.localized_name} ({resource_identity(route)})",
            )
            for route in resource_routes()
        ],
        key=resource_choice_label,
    )


def resource_choice_label(choice: tuple[str, str]) -> str:
    """Sort translated resource labels without altering their identities."""
    return choice[1].casefold()


def allowed_internal_resources(agent_id: str | UUID | None) -> set[str] | None:
    """Reload resource restrictions at discovery and execution; missing agents fail closed."""
    from bloomerp.models.agents import AIAgent

    if agent_id is None:
        return None
    try:
        agent = AIAgent.objects.only(
            "internal_resource_mode", "internal_resources"
        ).get(pk=agent_id)
    except (AIAgent.DoesNotExist, ValidationError, ValueError) as error:
        raise PermissionDenied("Agent resource configuration is unavailable") from error
    if agent.internal_resource_mode == "all":
        return None
    if agent.internal_resource_mode != "selected":
        return set()
    return set(agent.internal_resources)


def resource_tool_name(identity: str) -> str:
    """Generate a provider-safe tool name independent of translated resource titles."""
    return RESOURCE_TOOL_PREFIX + hashlib.sha256(identity.encode()).hexdigest()[:32]


def resource_tool_catalog(agent_id: str | UUID | None) -> dict[str, dict[str, Any]]:
    """Advertise each allowed reader as a tool while preserving resource contract metadata."""
    allowed = allowed_internal_resources(agent_id)
    tools: dict[str, dict[str, Any]] = {}
    for route in resource_routes():
        identity = resource_identity(route)
        if allowed is not None and identity not in allowed:
            continue
        contract = route.mcp
        schema = (
            contract.get_parameter_schema()
            if isinstance(contract, McpResourceTemplate)
            else {"type": "object", "properties": {}, "additionalProperties": False}
        )
        metadata = McpEndpointView._resource_definition(route)
        name = resource_tool_name(identity)
        tools[name] = {
            "name": name,
            "title": f"Read {metadata['title']}",
            "description": f"Read MCP resource {identity}. {metadata.get('description') or ''}",
            "inputSchema": schema,
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            "_meta": {"bloomerp/resource": metadata},
        }
    return tools


def require_resource_uri(agent_id: str | UUID | None, uri: Any) -> None:
    """Check the resolved reader, including concrete resources that shadow templates."""
    if not isinstance(uri, str):
        raise PermissionDenied("Invalid MCP resource URI")
    resolved = router.resolve_mcp_resource(uri)
    allowed = allowed_internal_resources(agent_id)
    if resolved is None or (
        allowed is not None and resource_identity(resolved[0]) not in allowed
    ):
        raise PermissionDenied("Internal MCP resource is not allowed for this agent")


def resource_tool_uri(
    agent_id: str | UUID | None, name: str, arguments: dict[str, Any]
) -> str:
    """Validate arguments and expand a permitted reader's URI before protocol dispatch."""
    definition = resource_tool_catalog(agent_id).get(name)
    if definition is None:
        raise PermissionDenied("Internal MCP resource is not allowed for this agent")
    Draft202012Validator(definition["inputSchema"], registry=Registry()).validate(
        arguments
    )
    metadata = definition["_meta"]["bloomerp/resource"]
    if "uri" in metadata:
        uri = metadata["uri"]
    else:
        uri = metadata["uriTemplate"]
        for variable in RESOURCE_VARIABLE_PATTERN.findall(uri):
            value = arguments[variable]
            if not isinstance(value, str):
                raise ValidationError("Resource template arguments must be strings")
            uri = uri.replace("{" + variable + "}", quote(value, safe=""))
    require_resource_uri(agent_id, uri)
    resolved = router.resolve_mcp_resource(uri)
    if resolved is None or resource_tool_name(resource_identity(resolved[0])) != name:
        raise PermissionDenied("Resource URI resolves to a different reader")
    return uri
