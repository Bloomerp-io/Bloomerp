"""Navigate all of the authenticated caller's tabs or one explicitly selected tab."""

from typing import Any
from urllib.parse import urlsplit

from asgiref.sync import async_to_sync
from django.http import HttpRequest
from django.urls import Resolver404, resolve
from django.utils.http import url_has_allowed_host_and_scheme
from rest_framework import serializers
from rest_framework.response import Response

from bloomerp.channels.agents.events import discover_browser_tabs, navigate_browser_tabs
from bloomerp.mcp.definition import McpTool
from bloomerp.mcp.schema import serializer_input_schema, serializer_output_schema
from bloomerp.router import router
from bloomerp.views.mcp.view_pages import UI_ROUTE_TYPES



class NavigateUserInputSerializer(serializers.Serializer):
    """Accept an instance-local URL and an optional explicit browser tab."""

    url = serializers.CharField(max_length=2048)
    tab_id = serializers.UUIDField(
        required=False,
        help_text="Target one tab from view_pages; omit to navigate all your connected tabs and devices.",
    )


class NavigationTabResultSerializer(serializers.Serializer):
    """Report delivery and acknowledgement separately for each browser connection."""

    success = serializers.BooleanField()
    status = serializers.ChoiceField(choices=["accepted", "completed", "dispatched", "failed"])
    url = serializers.CharField()
    tab_id = serializers.UUIDField()
    command_id = serializers.UUIDField(allow_null=True)
    result = serializers.DictField()


class NavigateUserOutputSerializer(serializers.Serializer):
    """Summarize navigation while retaining successful and failed per-tab outcomes."""

    success = serializers.BooleanField()
    status = serializers.ChoiceField(choices=["accepted", "completed", "dispatched", "partial", "failed"])
    url = serializers.CharField()
    results = NavigationTabResultSerializer(many=True)


def summarize_navigation_results(results: list[dict[str, Any]]) -> str:
    """Aggregate outcomes without claiming acknowledgement for timed-out connections."""
    statuses = {result["status"] for result in results}
    if statuses == {"failed"}:
        return "failed"
    if "failed" in statuses:
        return "partial"
    if "dispatched" in statuses:
        return "dispatched"
    return "completed" if statuses == {"completed"} else "accepted"


def normalize_navigation_url(request: HttpRequest, value: str) -> str:
    """Validate same-origin UI navigation and preserve query strings and fragments."""
    origin = urlsplit(request.build_absolute_uri("/"))
    target = urlsplit(value)
    if not url_has_allowed_host_and_scheme(value, {origin.netloc}, require_https=origin.scheme == "https"):
        raise ValueError("URL must belong to this Bloomerp instance")
    if target.netloc and (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
        raise ValueError("URL must belong to this Bloomerp instance")
    if not target.path.startswith("/") or value.startswith("//"):
        raise ValueError("Use an absolute instance URL or a path starting with /")
    try:
        match = resolve(target.path)
    except Resolver404 as exc:
        raise ValueError("URL does not resolve to a UI page") from exc
    if not any(route.url_name == match.url_name and route.route_type in UI_ROUTE_TYPES for route in router.get_routes()):
        raise ValueError("URL must resolve to a registered UI page")
    # The destination view still enforces its normal permissions on browser GET.
    return target._replace(scheme="", netloc="").geturl()


@router.register(
    name="Navigate user", url_name="navigate_user_mcp", route_type="mcp",
    description="Navigate all connected browser tabs, or one selected tab, to a Bloomerp UI page.",
    mcp=McpTool(
        title="Navigate user",
        description=(
            "Navigate the current user's browser to an instance-local UI URL. "
            "Use view_pages to discover URLs and browser tab IDs. Omit tab_id to navigate "
            "ALL of the current user's connected tabs and devices; provide tab_id to target "
            "one tab. Returns per-tab results, including partial failures. accepted means "
            "the browser received the command, not that the destination finished loading."
        ),
        input_schema=serializer_input_schema(NavigateUserInputSerializer),
        output_schema=serializer_output_schema(NavigateUserOutputSerializer),
        read_only_hint=True, 
        destructive_hint=False, 
        open_world_hint=False,
    ),
)
def navigate_user(request: HttpRequest) -> dict[str, Any] | Response:
    """Navigate the caller's selected tab or all connected tabs and report each result."""
    if not request.user.is_authenticated:
        return Response({"detail": "Authentication required"}, status=401)
    serializer = NavigateUserInputSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    try:
        url = normalize_navigation_url(request, serializer.validated_data["url"])
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=400)
    tabs = async_to_sync(discover_browser_tabs)(request.user.pk)
    tab_id = serializer.validated_data.get("tab_id")
    targets = [tab for tab in tabs if tab_id is None or tab.tab_id == str(tab_id)]
    if not targets or (tab_id is not None and len(targets) != 1):
        return Response({
            "detail": (
                "Open Bloomerp in a browser signed in as the MCP user, then retry"
                if not targets else "Multiple tabs match; supply a unique tab_id from view_pages"
            ),
            "browser_tabs": [tab.public_state() for tab in tabs],
        }, status=409)
    results = async_to_sync(navigate_browser_tabs)(targets, url)
    status = summarize_navigation_results(results)
    response = {
        "success": all(result["success"] for result in results),
        "status": status, "url": url, "results": results,
    }
    return Response(response, status=400) if status == "failed" else response
