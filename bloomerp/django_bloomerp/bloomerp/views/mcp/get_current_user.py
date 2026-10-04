"""Expose the authenticated caller's basic profile through MCP."""

from typing import Any

from django.http import HttpRequest
from rest_framework.response import Response

from bloomerp.mcp.definition import McpTool
from bloomerp.router import router


@router.register(
    name="Get current user",
    url_name="get_current_user",
    route_type="mcp",
    description="Return the authenticated user's basic profile.",
    mcp=McpTool(
        title="GetCurrentUser",
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": ["integer", "string"]},
                "email": {"type": "string"},
                "first_name": {"type": "string"},
                "last_name": {"type": "string"},
                "username": {"type": "string"},
            },
            "required": ["id", "email", "first_name", "last_name", "username"],
            "additionalProperties": False,
        },
        read_only_hint=True,
        open_world_hint=False,
    ),
)
def get_current_user(request: HttpRequest) -> dict[str, Any] | Response:
    """Return only the authenticated caller's ID and basic account fields."""
    user = request.user
    if not user.is_authenticated:
        return Response({"detail": "Authentication required"}, status=401)
    return {
        "id": user.pk,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username,
    }
