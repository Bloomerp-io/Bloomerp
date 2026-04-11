from bloomerp.model_fields.icon_field import IconField
from bloomerp.models.base_bloomerp_model import BloomerpModel
from django.db import models
from django.utils.translation import gettext_lazy as _


def get_tile_type_choices():
    from bloomerp.workspaces.tiles import TileType

    return [(tile.name, tile.value.name) for tile in TileType]

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
    type = models.CharField(
        help_text=_("The type of tile"),
        max_length=32,
        choices=get_tile_type_choices,
    )
    icon = IconField(
        default="fa fa-chart-simple"
    )
    schema = models.JSONField()
    auto_generated = models.BooleanField(
        default=False
    )

    string_search_fields = ['name', 'description']

    def __str__(self):
        return self.name
    
    
