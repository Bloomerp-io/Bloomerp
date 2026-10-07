"""Expose live workspace and tile authoring contracts to MCP clients."""

from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from bloomerp.mcp.definition import McpResource
from bloomerp.models.definition import FieldLayout
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.mcp.authoring_references import packaged_guide
from bloomerp.workspaces.base import TileTypeDefinition
from bloomerp.workspaces.registry import TILE_TYPE_REGISTRY


def tile_type_reference(key: str, definition: TileTypeDefinition) -> dict[str, Any]:
    """Describe a registered tile type without constructing or rendering a tile."""
    return {
        "type": key,
        "name": str(definition.name),
        "description": str(definition.description),
        "icon": definition.icon,
        "renderable": definition.model is not None and definition.render_cls is not None,
        "config_schema": (
            definition.model.model_json_schema(mode="validation")
            if definition.model is not None else None
        ),
    }


@router.register(
    name="Workspace authoring reference",
    url_name="workspace_resource",
    description="Create workspaces using mutations, layouts and live tile configuration schemas.",
    mcp=McpResource(
        uri="bloomerp://guides/create-workspace", mime_type="application/json",
    ),
)
def workspace_resource(request: HttpRequest) -> dict[str, Any]:
    """Return a construction guide and current tile schemas to authorized readers."""
    if not request.user.is_authenticated or not UserPolicyManager(request.user).has_global_permission(
        Workspace, [BloomerpPermission.VIEW],
    ):
        raise PermissionDenied("Access to workspaces is required to view this resource.")

    return {
        "guide": packaged_guide("create-workspace.md"),
        "models": {
            "workspace": Workspace._meta.label,
            "tile": Tile._meta.label,
        },
        "layout_schema": FieldLayout.model_json_schema(mode="validation"),
        "tile_types": [
            tile_type_reference(key, definition)
            for key, definition in TILE_TYPE_REGISTRY.items()
        ],
        "metadata_limits": (
            "Definitions and schemas are regenerated on each read, including installed extensions. "
            "This reference does not read saved tiles, workspaces, SQL data or object choices. "
            "Schemas describe configuration structure, not the caller's mutation permissions. "
            "Query column names and types must be verified through permitted SQL tools; "
            "x-field-types and x-choices-by-field-type describe constraints that JSON Schema "
            "cannot check against query results. Analytics schemas describe complete tiles; "
            "runtime validation may still accept incomplete editor drafts. "
            "Reading this resource does not create, render or execute anything."
        ),
    }
