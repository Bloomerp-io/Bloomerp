"""
Registry for BloomERP tile types. Each tile type is something that can be rendered on a workspace.

"""

from django.utils.translation import gettext_lazy as _

from bloomerp.utils.registry import BaseRegistry
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
from bloomerp.workspaces.analytics_tile.render import AnalyticsTileRenderer
from bloomerp.workspaces.base import TileTypeDefinition
from bloomerp.workspaces.canvas_tile.model import CanvasTileConfig
from bloomerp.workspaces.canvas_tile.render import CanvasTileRenderer
from bloomerp.workspaces.dataview_tile.form import DataViewTileForm
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig, dataview_tile_filter_fields_factory
from bloomerp.workspaces.analytics_tile.utils import analytics_tile_filter_field_factory
from bloomerp.workspaces.dataview_tile.render import DataViewTileRenderer
from bloomerp.workspaces.form_tile.model import FormTileConfig, FormTileForm
from bloomerp.workspaces.form_tile.render import FormTileRenderer
from bloomerp.workspaces.links_tile.model import LinkTileConfig
from bloomerp.workspaces.links_tile.render import LinksTileRenderer
from bloomerp.workspaces.text_tile.model import TextTileConfig
from bloomerp.workspaces.text_tile.render import TextTileRenderer


class TileTypeRegistry(BaseRegistry[TileTypeDefinition]):
    def choices(self) -> list[tuple[str, str]]:
        """Return model choices from the currently registered tile types."""
        return [(key, definition.name) for key, definition in self.items()]

    def key_for_config(self, config: object) -> str:
        """Return the registered key whose model accepts the supplied config."""
        for key, definition in self.items():
            if definition.model is not None and isinstance(config, definition.model):
                return key

        raise ValueError(
            f"No registered tile type accepts config '{type(config).__name__}'."
        )

TILE_TYPE_REGISTRY = TileTypeRegistry(TileTypeDefinition)

TILE_TYPE_REGISTRY.register(
    "ANALYTICS_TILE",
    TileTypeDefinition(
        name=str(_("Analytics Tile")),
        description=str(_("Visualizes data from a custom query and presents it in a structured format such as a chart, KPI, table, or pie chart.")),
        icon="fa-chart-line",
        form_cls=None, # TODO: Implement form for analytics tile configuration
        model=AnalyticsTileConfig,
        filter_fields_factory=analytics_tile_filter_field_factory,
        render_cls=AnalyticsTileRenderer
    )
)

TILE_TYPE_REGISTRY.register(
    "CANVAS_TILE",
    TileTypeDefinition(
        name=str(_("Canvas")),
        description=str(_("A free-form workspace where users can add and arrange different types of content such as text, media, and embedded components.")),
        icon="fa-palette",
        model=CanvasTileConfig,
        render_cls=CanvasTileRenderer,
    )
)

TILE_TYPE_REGISTRY.register(
    "LINKS_TILE",
    TileTypeDefinition(
        name=str(_("Links")),
        description=str(_("Provides quick access to a collection of internal or external links, allowing users to navigate efficiently to frequently used resources.")),
        icon="fa-link",
        model=LinkTileConfig,
        render_cls=LinksTileRenderer,
    )
)

TILE_TYPE_REGISTRY.register(
    "TEXT_TILE",
    TileTypeDefinition(
        name=str(_("Text")),
        description=str(_("Displays simple markdown content such as notes, instructions, or reference text.")),
        icon="fa-align-left",
        model=TextTileConfig,
        render_cls=TextTileRenderer,
    )
)

TILE_TYPE_REGISTRY.register(
    "DATAVIEW_TILE",
    TileTypeDefinition(
        name=str(_("Data View")),
        description=str(_("Displays and manages records from a selected model in a structured view with filtering, sorting, and interaction capabilities.")),
        icon="fa-table",
        form_cls=DataViewTileForm,
        model=DataViewTileConfig,
        render_cls=DataViewTileRenderer,
        filter_fields_factory=dataview_tile_filter_fields_factory,
    )
)

TILE_TYPE_REGISTRY.register(
    "FORM_TILE",
    TileTypeDefinition(
        name=str(_("Form")),
        description=str(_("Displays a form, containing inputs, etc.")),
        icon="fa-rectangle-list",
        form_cls=FormTileForm,
        model=FormTileConfig,
        render_cls=FormTileRenderer,
    )
)





