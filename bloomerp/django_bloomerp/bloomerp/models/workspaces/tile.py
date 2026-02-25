from bloomerp.models.base_bloomerp_model import BloomerpModel
from django.db import models
from enum import Enum
from dataclasses import dataclass
from django.forms import Field
from django.utils.translation import gettext_lazy as _

class Tile(BloomerpModel):
    """
    A widget represents a visual item that can be placed on a workspace.
    It takes in a query as entry point.
    """
    
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_tile'
    
    name = models.CharField(max_length=255, help_text=_("Name of the widget"))
    description = models.TextField(blank=True, null=True, help_text=_("Description of the widget"))
    query = models.ForeignKey(to="SqlQuery", on_delete=models.CASCADE, help_text=_("SQL query that represents the entry point for the widget"))
    schema = models.JSONField()

    string_search_fields = ['name', 'description']

    def __str__(self):
        return self.name
    
    
