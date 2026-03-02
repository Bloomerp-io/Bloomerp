from bloomerp.models.base_bloomerp_model import BloomerpModel
from django.db import models
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel
from enum import Enum

class TileTypeDefinition(BaseModel):
    name:str
    description:str
    icon:str = "" # Font awesom icon
    

class AnalyticsTile(BaseModel):
    query:str
    

class TileType(Enum):
    ANALYTICS_TILE = TileTypeDefinition(
        name=str(_("Analytics Tile")),
        description=str(_("Visualizes data from a custom query and presents it in a structured format such as a chart, KPI, table, or pie chart.")),
        icon="fa-chart-line",
    )
    
    CANVAS_TILE = TileTypeDefinition(
        name=str(_("Canvas")),
        description=str(_("A free-form workspace where users can add and arrange different types of content such as text, media, and embedded components.")),
        icon="fa-palette"
    )
    
    LINK_TILE = TileTypeDefinition(
        name=str(_("Link")),
        description=str(_("Provides quick access to a collection of internal or external links, allowing users to navigate efficiently to frequently used resources.")),
        icon="fa-link"
    )
    
    DATA_VIEW_TILE = TileTypeDefinition(
        name=str(_("Data View")),
        description=str(_("Displays and manages records from a selected model in a structured view with filtering, sorting, and interaction capabilities.")),
        icon="fa-table"
    )
    
    

    @classmethod
    def from_key(cls, key: str | None) -> "TileType | None":
        if not key:
            return None

        normalized_key = key.strip().upper()
        if not normalized_key:
            return None

        return cls.__members__.get(normalized_key)
    
    
    
    
    
    
    
    

class Tile(BloomerpModel):
    """
    A widget represents a visual item that can be placed on a workspace.
    """
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_tile'
    
    name = models.CharField(
        max_length=255, 
        help_text=_("Name of the widget")
        )
    description = models.TextField(
        blank=True,
        null=True,
        help_text=_("Description of the widget")
        )
    schema = models.JSONField()

    string_search_fields = ['name', 'description']

    def __str__(self):
        return self.name
    
    
