from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Type

from django.forms import CharField, Field, Form
from django.utils.translation import gettext_lazy as _
from enum import Enum
from pydantic import BaseModel

if TYPE_CHECKING:
    from bloomerp.workspaces.tiles import BaseTileRenderer

@dataclass
class OptionDefinition:
    key: str
    label: str
    description: str
    field_cls: type[Field]
    field_args: dict[str, object] = field(default_factory=dict)


@dataclass
class FieldDefinition:
    key: str
    label: str
    icon:str
    description: str
    opts: list[OptionDefinition] = field(default_factory=list)

@dataclass
class AnalyticsTileTypeDefinition:
    key: str
    name: str
    description: str
    icon: str = ""  # Font awesome icon
    render_cls: type[BaseTileRenderer] | None = None
    fields: list[FieldDefinition] = field(default_factory=list)


LABEL_FIELD = OptionDefinition(
    key="label_field",
    label=_("Label Field"),
    description=_("The field to be used as the label for the data points in the visualization."),
    field_cls=CharField,
    field_args={},
)



class AnalyticsTileType(Enum):
    TWO_DIM_CHART = AnalyticsTileTypeDefinition(
        key="TWO_DIM_CHART",
        name=str(_("2D Chart")),
        description=str(_("Visualizes data from a custom query in a two-dimensional chart format, allowing users to easily identify trends, patterns, and insights through graphical representation.")),
        icon="fa-chart-bar",
        fields=[
            FieldDefinition(
                key="x_axis",
                label=_("X-Axis"),
                icon="fa-solid fa-x",
                description=_("The field to be used for the X-axis of the chart."),
                opts=[
                    LABEL_FIELD
                ]
            ),
            FieldDefinition(
                key="y_axis",
                label=_("Y-Axis"),
                icon="fa-solid fa-y",
                description=_("The field to be used for the Y-axis of the chart."),
                opts=[
                    LABEL_FIELD
                ]
            ),
        ]
    )

    TABLE = AnalyticsTileTypeDefinition(
        key="TABLE",
        name=str(_("Table")),
        description=str(_("Displays data from a custom query in a structured tabular format, enabling users to view, sort, and analyze information in rows and columns for easy comparison and reference.")),
        icon="fa-table",
    )

    KPI = AnalyticsTileTypeDefinition(
        key="KPI",
        name=str(_("KPI")),
        description=str(_("Presents key performance indicators (KPIs) derived from a custom query in a concise and visually impactful format, allowing users to quickly assess critical metrics and track progress towards specific goals.")),
        icon="fa-tachometer-alt",
    )

    THREE_DIM_CHART = AnalyticsTileTypeDefinition(
        key="THREE_DIM_CHART",
        name=str(_("3D Chart")),
        description=str(_("Visualizes data from a custom query in a three-dimensional chart format, providing users with an immersive and interactive way to explore complex datasets, identify relationships, and gain deeper insights through a multi-dimensional graphical representation.")),
        icon="fa-cubes",
    )

    PIVOT_TABLE = AnalyticsTileTypeDefinition(
        key="PIVOT_TABLE",
        name=str(_("Pivot Table")),
        description=str(_("Displays data from a custom query in a pivot table format, allowing users to dynamically summarize, analyze, and explore large datasets by rearranging and aggregating data across multiple dimensions for enhanced insights and decision-making.")),
        icon="fa-th",
    )

    MAP = AnalyticsTileTypeDefinition(
        key="MAP",
        name=str(_("Map")),
        description=str(_("Visualizes geospatial data from a custom query on an interactive map, enabling users to identify spatial patterns, trends, and insights by plotting data points, regions, or heatmaps based on geographic locations for enhanced analysis and decision-making.")),
        icon="fa-map-marked-alt",
    )

    PIE_CHART = AnalyticsTileTypeDefinition(
        key="PIE_CHART",
        name=str(_("Pie Chart")),
        description=str(_("Visualizes data from a custom query in a pie chart format, allowing users to easily understand the proportional distribution of different categories or segments within a dataset, making it ideal for displaying parts of a whole and comparing relative sizes for enhanced insights and decision-making.")),
        icon="fa-chart-pie",
    )

    @classmethod
    def from_key(cls, key: str) -> "AnalyticsTileTypeDefinition":
        for item in cls:
            if item.value.key == key:
                return item.value
        raise ValueError(f"Unsupported analytics tile type: {key}")


# Todo: make sure the field config is integrated with 
class FieldConfig(BaseModel):
    name:str
    opts:dict

class AnalyticsTileConfig(BaseModel):
    query:str
    type:str # Must be one of the supported types
    fields:dict[str, FieldConfig]
    opts:dict


# -------------------------------
# Utility functions
# -------------------------------

def analytics_tile_form_factory() -> Type[Form]:
    pass