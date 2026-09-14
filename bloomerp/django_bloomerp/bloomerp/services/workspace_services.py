from copy import copy
from typing import Any

from django.db import transaction
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext

from bloomerp.models import LayoutItem
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.models.workspaces.tile import Tile
from bloomerp.modules.definition import ModuleRegistry, module_registry
from bloomerp.workspaces.analytics_tile.utils import TileFieldType
from bloomerp.workspaces.base import BaseTileConfig
from bloomerp.workspaces.links_tile.model import Link, LinkTileConfig
from bloomerp.workspaces.registry import TILE_TYPE_REGISTRY
from bloomerp.models.users import User
from bloomerp.services.sectioned_layout_services import AvailableLayoutItem
from django.db.models import Q
from django.forms import Form
from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY

PRIMITIVE_FIELD_TYPE_MAP = {
    TileFieldType.TEXT.value.key: FIELD_TYPE_REGISTRY.CHAR_FIELD,
    TileFieldType.NUMERIC.value.key: FIELD_TYPE_REGISTRY.DECIMAL_FIELD,
    TileFieldType.DATE.value.key: FIELD_TYPE_REGISTRY.DATE_FIELD,
    TileFieldType.DATETIME.value.key: FIELD_TYPE_REGISTRY.DATE_TIME_FIELD,
    TileFieldType.BOOL.value.key: FIELD_TYPE_REGISTRY.BOOLEAN_FIELD,
}



def select_workspace(workspace: Workspace, user: User) -> Workspace:
    """Select an owned or shared workspace for the user's module scope."""
    from bloomerp.services.preference_services import PreferenceManager

    return PreferenceManager(user).select(workspace)


def resolve_tile_type_from_config(config: BaseTileConfig) -> str:
    """Resolves the tile type from the config by checking which class it's using.

    Args:
        config (BaseTileConfig): the config object

    Returns:
        str: the tile type
    """
    return TILE_TYPE_REGISTRY.key_for_config(config)


def _serialize_default_tile_config(tile_config: BaseTileConfig) -> dict[str, Any]:
    schema = tile_config.model_dump(mode="json")
    if not isinstance(tile_config, LinkTileConfig):
        return schema

    def resolve_links(links: list[dict[str, Any]]) -> None:
        for link in links:
            url_name = str(link.get("url_name") or "").strip()
            if url_name:
                link["url"] = reverse(url_name)
            resolve_links(link.get("children") or [])

    resolve_links(schema["links"])
    return schema


def create_or_update_default_tiles(
    registry: ModuleRegistry | None = None,
) -> dict[str, Tile]:
    """Creates or updates the default tiles from models and modules

    Returns:
        dict[str, Tile]: dictionary of the native tile ID's together with their tile database objects.
    """
    registry = registry or module_registry

    existing_tiles: dict[str, Tile] = {}
    for tile in Tile.get_default_tiles():
        tile_id = str(tile.schema.get("id") or "").strip()
        if not tile_id:
            continue
        if tile_id in existing_tiles:
            raise ValueError(
                f"Multiple auto-generated tiles use native id '{tile_id}'."
            )
        existing_tiles[tile_id] = tile

    tile_configs: dict[str, BaseTileConfig] = {}
    for module_id in registry.get_all():
        for tile_config in registry.get_tiles_for_module(module_id):
            tile_id = str(tile_config.id or "").strip()
            if not tile_id:
                raise ValueError("Every declarative tile must have a native id.")
            if tile_id in tile_configs:
                raise ValueError(
                    f"Duplicate declarative tile id '{tile_id}' found across modules."
                )
            tile_configs[tile_id] = tile_config

    default_icon = Tile._meta.get_field("icon").get_default()
    synchronized: dict[str, Tile] = {}

    with transaction.atomic():
        for tile_id, tile_config in tile_configs.items():
            values = {
                "name": tile_config.name or tile_id,
                "description": tile_config.description,
                "icon": tile_config.icon or default_icon,
                "type": resolve_tile_type_from_config(tile_config),
                "schema": _serialize_default_tile_config(tile_config),
                "auto_generated": True,
            }
            existing_tile = existing_tiles.get(tile_id)

            if existing_tile is None:
                tile = Tile.objects.create(**values)
            else:
                tile = existing_tile
                for field, value in values.items():
                    setattr(tile, field, value)
                tile.save(update_fields=[*values, "datetime_updated"])

            synchronized[tile_id] = tile

    return synchronized


def render_tile_to_string(
    tile:Tile, 
    request:HttpRequest
    ) -> str:
    """Renders a tile to a string, given the tile and the user object

    Args:
        tile (Tile): the tile object
        user (User): the user object

    Returns:
        str: the html string
    """
    # 1. Get the tile type
    tile_type = TILE_TYPE_REGISTRY.get(tile.type)
    if tile_type is None:
        raise ValueError(f"Unknown tile type '{tile.type}'.")
    if tile_type.model is None or tile_type.render_cls is None:
        raise ValueError(f"Tile type '{tile.type}' cannot be rendered.")

    # 2. Get the config object
    config = tile_type.model(
        **tile.schema
    )

    if tile.auto_generated and isinstance(config, LinkTileConfig):
        _localize_generated_module_links(config.links)

    # 3. Get the render class. Saved canvases receive their persistence context;
    # previews call the renderer directly without a Tile instance.
    render_kwargs = {"tile": tile} if tile.type == "CANVAS_TILE" else {}
    return tile_type.render_cls.render(config=config, request=request, **render_kwargs)


def _module_for_generated_tile(tile: Tile):
    if not tile.auto_generated:
        return None
    return next(
        (
            module
            for module in module_registry.get_all().values()
            if module.name == tile.name
        ),
        None,
    )


def _localize_generated_module_links(links: list[Link]) -> None:
    modules_by_path = {
        f"/{module.route_path}/": module
        for module in module_registry.get_all().values()
        if module.route_path
    }
    for link in links:
        module = modules_by_path.get(link.url)
        if module is not None and link.name == module.name:
            link.name = module.localized_name
        _localize_generated_module_links(link.children)


def _tile_display_metadata(tile: Tile) -> tuple[str, str | None]:
    module = _module_for_generated_tile(tile)
    if module is None:
        return tile.name, tile.description

    name = module.localized_name
    links = tile.schema.get("links", []) if isinstance(tile.schema, dict) else []
    is_module_navigation = any(
        link.get("url") == f"/{module.route_path}/"
        for link in links
        if isinstance(link, dict)
    )
    if is_module_navigation:
        source_description = f"Navigate to the '{module.name}' module."
        description = (
            gettext("Navigate to the '{module}' module.").format(module=name)
            if tile.description == source_description
            else tile.description
        )
    else:
        source_description = (
            f"Links to the different models of the '{module.name}' module."
        )
        description = (
            gettext("Links to the different models of the '{module}' module.").format(
                module=name
            )
            if tile.description == source_description
            else tile.description
        )
    return name, description


def build_workspace_layout_item(
    *,
    tile: Tile,
    request: HttpRequest,
    colspan: int = 1,
    config: dict | None = None,
    workspace_id: str | None = None,
    render_content: bool = True,
) -> LayoutItem:
    """Build a tile layout item, optionally deferring its expensive body render."""
    content = ""
    if render_content:
        render_request = copy(request)
        render_request.GET = request.GET.copy()
        for transport_param in ("colspan", "max_cols"):
            render_request.GET.pop(transport_param, None)
        render_request.GET["tile_id"] = str(tile.pk)
        if workspace_id is not None:
            from bloomerp.filters.resolver import FilterFieldResolver

            workspace = FilterFieldResolver.for_user(
                "workspace", workspace_id, request.user
            ).workspace
            render_request.GET = workspace.apply_default_filters(render_request.GET)
            render_request.GET["workspace_id"] = str(workspace_id)

        try:
            content = render_tile_to_string(tile, render_request)
        except Exception as exc:
            content = format_html('<div class="alert alert-danger">{}</div>', exc)

    tile_name, _tile_description = _tile_display_metadata(tile)

    return LayoutItem(
        id=str(tile.pk),
        colspan=colspan,
        config=config or {},
        icon=tile.icon,
        label=tile_name,
        content=content,
        component_name="workspace-tile",
        border=True,
        edit_url=(
            f"{reverse('tiles_detail_update_tile', kwargs={'pk': tile.pk})}"
            "?reset_wizard=true"
        ),
        search_keywords=tile.get_type_display(),
    )



class UserWorkspaceService:
    def __init__(self, user:User):
        self.user = user

    def get_available_workspace_tiles(self) -> list[dict[str, Any]]:
        """Returns the available workspace tiles for a particular user

        Returns:
            list[dict[str, Any]]: the list of dictionaries containing the workspace tiles
        """
        # Or created by user OR auto generated
        
        tiles = Tile.objects.filter(
            Q(created_by=self.user) | Q(auto_generated=True)
        )
        available_tiles = []
        for tile in tiles:
            title, description = _tile_display_metadata(tile)
            available_tiles.append(
                AvailableLayoutItem(
                    id=tile.id,
                    title=title,
                    description=description,
                    icon=tile.icon,
                    search_keywords=tile.get_type_display(),
                )
            )
        return available_tiles

        
