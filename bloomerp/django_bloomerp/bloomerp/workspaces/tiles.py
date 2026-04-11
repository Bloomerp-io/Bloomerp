
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from enum import Enum

from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
from bloomerp.workspaces.analytics_tile.render import AnalyticsTileRenderer
from bloomerp.workspaces.canvas_tile.model import CanvasTileConfig
from bloomerp.workspaces.canvas_tile.render import CanvasTileRenderer
from bloomerp.workspaces.dataview_tile.form import DataViewTileForm
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig
from bloomerp.workspaces.dataview_tile.render import DataViewTileRenderer
from bloomerp.workspaces.links_tile.model import LinkTileConfig
from bloomerp.workspaces.links_tile.render import LinksTileRenderer
from bloomerp.workspaces.base import TileTypeDefinition


class TileType(Enum):
    ANALYTICS_TILE = TileTypeDefinition(
        name=str(_("Analytics Tile")),
        description=str(_("Visualizes data from a custom query and presents it in a structured format such as a chart, KPI, table, or pie chart.")),
        icon="fa-chart-line",
        form_cls=None, # TODO: Implement form for analytics tile configuration
        model=AnalyticsTileConfig,
        render_cls=AnalyticsTileRenderer
    )

    CANVAS_TILE = TileTypeDefinition(
        name=str(_("Canvas")),
        description=str(_("A free-form workspace where users can add and arrange different types of content such as text, media, and embedded components.")),
        icon="fa-palette",
        model=CanvasTileConfig,
        render_cls=CanvasTileRenderer
    )

    LINKS_TILE = TileTypeDefinition(
        name=str(_("Links")),
        description=str(_("Provides quick access to a collection of internal or external links, allowing users to navigate efficiently to frequently used resources.")),
        icon="fa-link",
        model=LinkTileConfig,
        render_cls=LinksTileRenderer
    )

    # DATAVIEW_TILE = TileTypeDefinition(
    #     name=str(_("Data View")),
    #     description=str(_("Displays and manages records from a selected model in a structured view with filtering, sorting, and interaction capabilities.")),
    #     icon="fa-table",
    #     form_cls=DataViewTileForm,
    #     model=DataViewTileConfig,
    #     render_cls=DataViewTileRenderer
    # )

    @classmethod
    def from_key(cls, key: str | None) -> "TileType | None":
        if not key:
            return None

        normalized_key = key.strip().upper()
        if not normalized_key:
            return None

        return cls.__members__.get(normalized_key)
    

