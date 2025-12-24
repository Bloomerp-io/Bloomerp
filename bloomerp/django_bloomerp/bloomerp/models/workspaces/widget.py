from bloomerp.models.base_bloomerp_model import BloomerpModel
from django.db import models
from enum import Enum
from dataclasses import dataclass
from django.forms import Field
from django.utils.translation import gettext_lazy as _

class WidgetType(Enum):
    CHART = 'chart'
    TABLE = 'table'
    KPI = 'kpi'
    LINK = "link"
    
class ChartType(Enum):
    BAR = 'bar'
    LINE = 'line'
    PIE = 'pie'
    
@dataclass
class OptionField:
    key : str
    label : str
    field_type : Field
    description : str | None = None

@dataclass
class ShelveTypeImplementation:
    key : str
    name : str
    description : str
    widget_type : WidgetType
    option_fields : list[OptionField]

class ShelveType(Enum):
    def _missing_(cls, value):
        for member in cls:
            if member.value["key"] == value:
                return member
        raise ValueError(f"{value} is not a valid {cls.__name__}")
    
    
    X_AXIS = {
        "key" : "x_axis",
        "name" : "X-Axis",
        "description" : "The horizontal axis for a chart",
        "widget_type" : WidgetType.CHART,
        "option_fields" : [
            OptionField("label", "Label", "The label of the x-axis")
        ]
    }
    
    Y_AXIS = {
        "key" : "y_axis",
        "name" : "Y-Axis",
        "description" : "The vertical axis for a chart",
        "widget_type" : WidgetType.CHART,
        "option_fields" : [
            OptionField("label", "Label", "The label of the y-axis")
        ]
    }
    
    COLUMN = {
        "key" : "column",
        "name" : "Columns",
        "description" : "The column you want to see in the table",
        "widget_type" : WidgetType.TABLE,
        "option_fields" : [
            OptionField("label", "Label", "The label of the x-axis"),
            OptionField("formatting", "Formatting", "The formatting you want to apply on the column")
        ]
    }
        
class Widget(BloomerpModel):
    """
    A widget represents a visual item that can be placed on a workspace.
    It takes in a query as entry point.
    """
    
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_widget'
    
    name = models.CharField(max_length=255, help_text=_("Name of the widget"))
    description = models.TextField(blank=True, null=True, help_text=_("Description of the widget"))
    query = models.ForeignKey(to="SqlQuery", on_delete=models.CASCADE, help_text=_("SQL query that represents the entry point for the widget"))
    widget_type = models.CharField(
        max_length=30,
        choices=[(wt.value, wt.name) for wt in WidgetType],
        help_text=_("Type of widget")
    )
    schema = models.JSONField()

    string_search_fields = ['name', 'description']

    def __str__(self):
        return self.name
    
    
