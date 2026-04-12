from typing import Any

from django.db import transaction
from django.urls import reverse

from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.models.workspaces.tile import Tile
from bloomerp.modules.definition import module_registry
from bloomerp.utils.models import get_list_view_url
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileType
from bloomerp.workspaces.base import TileTypeDefinition
from bloomerp.workspaces.links_tile.model import Link, LinkTileConfig
from bloomerp.workspaces.tiles import TileType
from bloomerp.models.users import User
from bloomerp.services.sectioned_layout_services import AvailableLayoutItem
from django.db.models import Q

def create_default_workspace(
        user,
        module_id:str
):
    """
    Creates the default workspace for a particular user and module.
    """
    workspace = Workspace.get_default_for_user(user=user, module_id=module_id)
    if workspace:
        return workspace

    workspace = Workspace.objects.create(
        user=user,
        name="Default",
        module_id=module_id,
        is_default=True,
        layout={
            "rows": [
                {
                    "title": None,
                    "columns": 4,
                    "items": [],
                }
            ]
        },
    )

    ensure_default_workspace_tiles_for_module(user, module_id)
    return workspace


def set_default_workspace(workspace: Workspace, user: User) -> Workspace:
    if workspace.user_id != user.id:
        raise PermissionError("Only the workspace owner can set a default workspace.")

    if not workspace.module_id:
        raise ValueError("Only module or submodule workspaces can be set as default.")

    with transaction.atomic():
        Workspace.objects.filter(
            user=user,
            module_id=workspace.module_id,
            sub_module_id=workspace.sub_module_id,
            is_default=True,
        ).exclude(pk=workspace.pk).update(is_default=False)

        if not workspace.is_default:
            workspace.is_default = True
            workspace.save(update_fields=["is_default"])

    return workspace


def ensure_default_workspace_tiles_for_module(user, module_id: str) -> None:
    module = module_registry.get(module_id)
    if not module:
        return

    if module.sub_modules and len(module.sub_modules) > 1:
        for sub_module in module.sub_modules:
            links = []
            models = module_registry.get_models_for_submodule(module_id, sub_module.id)

            for model in models:
                url = reverse(get_list_view_url(model))
                name = model._meta.verbose_name_plural
                links.append(
                    Link(
                        url=url,
                        name=name,
                        is_internal=True
                    )
                )
            
            config = LinkTileConfig(links=links).model_dump()
            description = f"Links to the different models of the '{sub_module.name}' module."

            Tile.objects.get_or_create(
                created_by=user,
                updated_by=user,
                name=sub_module.name,
                type=TileType.LINKS_TILE.name,
                description=description,
                schema=config,
                auto_generated=True
            )


def create_default_sidebar(
        user,
):
    modules = module_registry.get_enabled()
    

def render_tile_to_string(tile:Tile, user:User) -> str:
    """Renders a tile to a string, given the tile and the user object

    Args:
        tile (Tile): the tile object
        user (User): the user object

    Returns:
        str: the html string
    """
    # 1. Get the tile type
    tile_type = TileType.from_key(tile.type)

    # 2. Get the config object
    config = tile_type.value.model(**tile.schema)

    # 3. Get the render class
    return tile_type.value.render_cls.render(
        config=config,
        user=user
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
        return [
            AvailableLayoutItem(
            id=tile.id,
            title=tile.name,
            description=tile.description,
            icon=tile.icon
        ) for tile in tiles]

        
