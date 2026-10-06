"""Resolve current agent tool restrictions independently of actor permissions."""

from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError

from bloomerp.mcp.view import McpEndpointView
from bloomerp.router import router


def internal_tool_choices() -> list[tuple[str, str]]:
    """Build labels from the live MCP registry, including instance extensions."""
    choices = []
    for route in router.get_mcp_routes():
        definition = McpEndpointView._tool_definition(route)
        name = definition["name"]
        label = definition.get("title") or route.localized_name or name
        choices.append((name, f"{label} ({name})"))
    return sorted(choices, key=tool_choice_label)


def tool_choice_label(choice: tuple[str, str]) -> str:
    """Sort translated tool labels consistently without changing stable names."""
    return choice[1].casefold()


def allowed_internal_tools(agent_id: str | UUID | None) -> set[str] | None:
    """Reload restrictions for every dispatch; missing configured agents fail closed."""
    from bloomerp.models.agents import AIAgent

    # Older runtime configurations without an agent record retain their behavior.
    if agent_id is None:
        return None
    try:
        agent = AIAgent.objects.only("internal_tool_mode", "internal_tools").get(
            pk=agent_id
        )
    except (AIAgent.DoesNotExist, ValidationError, ValueError) as error:
        raise PermissionDenied("Agent tool configuration is unavailable") from error
    if agent.internal_tool_mode == AIAgent.InternalToolMode.ALL:
        return None
    if agent.internal_tool_mode != AIAgent.InternalToolMode.SELECTED:
        return set()
    return {name for name in agent.internal_tools if isinstance(name, str)}


def require_internal_tool(agent_id: str | UUID | None, name: Any) -> None:
    """Reject tools excluded by the current agent before proposing or executing effects."""
    if not isinstance(name, str):
        raise PermissionDenied("Invalid internal MCP tool name")
    allowed = allowed_internal_tools(agent_id)
    if allowed is not None and name not in allowed:
        raise PermissionDenied("Internal MCP tool is not allowed for this agent")
