"""Discover searchable UI pages and the caller's connected browser tabs."""

import logging
from typing import Any

from asgiref.sync import async_to_sync
from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse
from rest_framework import serializers
from rest_framework.response import Response

from bloomerp.channels.agents.events import discover_browser_tabs
from bloomerp.mcp.definition import McpTool
from bloomerp.mcp.schema import serializer_input_schema, serializer_output_schema
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import BloomerpRoute, RouteType, ViewType, router

logger = logging.getLogger(__name__)
UI_ROUTE_TYPES = {RouteType.APP, RouteType.MODULE, RouteType.MODEL, RouteType.DETAIL}


class ViewPagesInputSerializer(serializers.Serializer):
    """Search and paginate directly navigable UI routes."""

    search = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    module = serializers.CharField(required=False, max_length=100)
    model = serializers.CharField(required=False, max_length=100)
    route_type = serializers.ChoiceField(required=False, choices=["app", "module", "model", "detail"])
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=25)


class ViewPagesOutputSerializer(serializers.Serializer):
    """Return page matches alongside current browser targets."""

    pages = serializers.ListField(child=serializers.DictField())
    browser_tabs = serializers.ListField(child=serializers.DictField())
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    total_results = serializers.IntegerField()


def can_discover_page(request: HttpRequest, route: BloomerpRoute) -> bool:
    """Check existing view gates without executing a page or its side effects."""
    if route.view_type == ViewType.FUNCTION:
        return route.model is None or UserPolicyManager(request.user).has_global_permission(
            route.model, BloomerpPermission.VIEW,
        )
    try:
        view = route.view(**router._get_route_kwargs(route))
        view.setup(request)
        if hasattr(view, "staff_access_required"):
            if view.staff_access_required() and not request.user.is_staff:
                return False
        return bool(view.has_permission()) if hasattr(view, "has_permission") else True
    except Exception:
        logger.debug("Cannot establish page visibility for %s", route.url_name, exc_info=True)
        return False


@router.register(
    name="View pages", url_name="view_pages", route_type="mcp",
    description="Find searchable UI pages and connected browser tabs for navigation.",
    mcp=McpTool(
        title="View pages",
        description=(
            "Search directly navigable Bloomerp UI pages by name, description, or route. "
            "Optional module ID, model label (app.Model), and route type filters. "
            "Routes requiring path arguments are excluded. Also returns this user's live "
            "browser_tabs; pass a tab_id and page URL to navigate_user_mcp."
        ),
        input_schema=serializer_input_schema(ViewPagesInputSerializer),
        output_schema=serializer_output_schema(ViewPagesOutputSerializer),
        read_only_hint=True, open_world_hint=False,
    ),
)
def view_pages(request: HttpRequest) -> dict[str, Any] | Response:
    """Search permission-gated pages and discover the authenticated caller's tabs."""
    if not request.user.is_authenticated:
        return Response({"detail": "Authentication required"}, status=401)
    serializer = ViewPagesInputSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    options = serializer.validated_data
    query = options["search"].casefold()
    pages: list[dict[str, Any]] = []
    for route in router.get_routes():
        if route.route_type not in UI_ROUTE_TYPES or not route.searchable or route.nr_of_args():
            continue
        module_id = route.module.id if route.module else None
        model_label = route.model._meta.label if route.model else None
        if options.get("module") and options["module"].casefold() != (module_id or "").casefold():
            continue
        if options.get("model") and options["model"].casefold() != (model_label or "").casefold():
            continue
        if options.get("route_type") and options["route_type"] != route.route_type.value:
            continue
        name, description = route.localized_name, route.localized_description
        if query not in f"{name} {description} {route.url_name} {route.path}".casefold():
            continue
        try:
            url = reverse(route.url_name)
        except NoReverseMatch:
            continue
        if not can_discover_page(request, route):
            continue
        pages.append({
            "name": name, "description": description, "url_name": route.url_name,
            "url": url, "route_type": route.route_type.value, "module": module_id,
            "model": model_label,
        })
    page, page_size = options["page"], options["page_size"]
    start = (page - 1) * page_size
    tabs = async_to_sync(discover_browser_tabs)(request.user.pk)
    return {
        "pages": pages[start:start + page_size],
        "browser_tabs": [tab.public_state() for tab in tabs],
        "page": page, "page_size": page_size, "total_results": len(pages),
        "total_pages": (len(pages) + page_size - 1) // page_size,
    }
