from typing import Type

from django.forms import Form
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from enum import Enum
from pydantic import BaseModel

from abc import ABC, abstractmethod

from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
from bloomerp.workspaces.canvas_tile.model import CanvasTileConfig
from bloomerp.workspaces.data_view_tile.form import DataViewTileForm
from bloomerp.workspaces.data_view_tile.model import DataViewTileConfig
from bloomerp.workspaces.links_tile.model import LinkTileConfig

class BaseTileRenderer(ABC):
    template_name: str = ""

    @abstractmethod
    def render(self, config: BaseModel) -> str:
        """
        Render the tile based on the provided configuration.

        Args:
            config (BaseModel): The configuration for the tile.

        Returns:
            str: The rendered HTML for the tile.
        """
        raise NotImplementedError("Subclasses must implement the render method.")

    def render_to_string(self, context: dict) -> str:
        """
        Render the tile using the specified template and context.

        Args:
            context (dict): The context data to be passed to the template.
        Returns:
            str: The rendered HTML for the tile.
        """        
        from django.template.loader import render_to_string
        return render_to_string(self.template_name, context)


class TileTypeDefinition(BaseModel):
    name:str
    description:str
    icon:str = "" # Font awesome icon
    form_cls:Type[Form] | None = None
    model:Type[BaseModel] | None = None
    render_cls:Type[BaseTileRenderer] | None = None


class TileType(Enum):
    ANALYTICS_TILE = TileTypeDefinition(
        name=str(_("Analytics Tile")),
        description=str(_("Visualizes data from a custom query and presents it in a structured format such as a chart, KPI, table, or pie chart.")),
        icon="fa-chart-line",
        form_cls=None, # TODO: Implement form for analytics tile configuration
        model=AnalyticsTileConfig,
    )

    CANVAS_TILE = TileTypeDefinition(
        name=str(_("Canvas")),
        description=str(_("A free-form workspace where users can add and arrange different types of content such as text, media, and embedded components.")),
        icon="fa-palette",
        model=CanvasTileConfig
    )

    LINKS_TILE = TileTypeDefinition(
        name=str(_("Links")),
        description=str(_("Provides quick access to a collection of internal or external links, allowing users to navigate efficiently to frequently used resources.")),
        icon="fa-link",
        model=LinkTileConfig,
    )

    DATA_VIEW_TILE = TileTypeDefinition(
        name=str(_("Data View")),
        description=str(_("Displays and manages records from a selected model in a structured view with filtering, sorting, and interaction capabilities.")),
        icon="fa-table",
        form_cls=DataViewTileForm,
        model=DataViewTileConfig,
    )

    @classmethod
    def from_key(cls, key: str | None) -> "TileType | None":
        if not key:
            return None

        normalized_key = key.strip().upper()
        if not normalized_key:
            return None

        return cls.__members__.get(normalized_key)