from enum import Enum
from dataclasses import dataclass
from django.forms import Field

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
    description : str | None = None
    field_type : Field

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
    
    
    