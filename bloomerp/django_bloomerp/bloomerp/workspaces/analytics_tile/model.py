from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Self, Optional, Type

from django.forms import BooleanField, CharField, ChoiceField, Field, Form
from django.utils.translation import gettext_lazy as _
from enum import Enum
from pydantic import BaseModel

from bloomerp.workspaces.analytics_tile.kpi import AnalyticsKpiRenderer
from bloomerp.workspaces.analytics_tile.table import AnalyticsTableRenderer
from bloomerp.workspaces.analytics_tile.two_dim_chart import AnalyticsTwoDimChartRenderer
from bloomerp.workspaces.analytics_tile.utils import (
    TileFieldType,
    get_aggregator_choices,
    get_formatter_choices,
    to_primitive_field_type,
)
from bloomerp.workspaces.base import BaseTileConfig, TileOperationDefinition, TileOperationHandler, TileOperationHandlerRespone


if TYPE_CHECKING:
    from bloomerp.workspaces.base import BaseTileRenderer

@dataclass
class OptionDefinition:
    """Describes one configurable option shown in a tile or field options form."""

    key: str
    label: str
    description: str
    field_cls: type[Field]
    field_args: dict[str, object] = field(default_factory=dict)
    restrict_to:Optional[list[TileFieldType]] = None # Only these types of fields are eligible for this type of field definition
    choices_provider: Optional[Callable[[TileFieldType | None], list[tuple[str, str]]]] = None

@dataclass
class FieldDefinition:
    """Describes one field slot that can be configured for an analytics tile."""

    key: str
    label: str
    icon:str
    description: str
    opts: list[OptionDefinition] = field(default_factory=list)
    allow_multiple: bool = True
    restrict_to:Optional[list[TileFieldType]] = None # Only these types of fields are eligible for this type of field definition

@dataclass
class AnalyticsTileTypeDefinition:
    """Describes one analytics tile type and the configuration it supports."""

    key: str
    name: str
    description: str
    icon: str = ""  # Font awesome icon
    render_cls: type[BaseTileRenderer] | None = None
    fields: list[FieldDefinition] = field(default_factory=list)
    opts: list[FieldDefinition] = field(default_factory=list)


LABEL_OPTION = OptionDefinition(
    key="label",
    label=_("Label"),
    description=_("The label"),
    field_cls=CharField,
    field_args={},
)

PREFIX_OPTION = OptionDefinition(
    key="prefix",
    label=_("Prefix"),
    description=_("Text that comes before the value"),
    field_cls=CharField,
    field_args={}
)

SUFFIX_OPTION = OptionDefinition(
    key="suffix",
    label=_("Suffix"),
    description=_("Text that comes after the value"),
    field_cls=CharField,
    field_args={}
)

FORMATTER_OPTION = OptionDefinition(
    "formatter",
    _("Formatter"),
    _("The formatter applied to this value"),
    field_cls=ChoiceField,
    choices_provider=get_formatter_choices,
)

COLOR_OPTION = OptionDefinition(
    "color",
    _("Color"),
    _("Optional color for this series, for example #3b82f6."),
    CharField,
)

SIZE_OPTION = OptionDefinition(
    "size",
    _("Size"),
    _("The size"),
    CharField,
    {
        "choices" : [
            ("S","S"),
            ("M","M"),
            ("L","L")
        ]
    }
)

CHART_TYPE_OPTION = OptionDefinition(
    "chart_type",
    _("Chart type"),
    _("How the series should be drawn."),
    ChoiceField,
    {
        "choices": [
            ("line", _("Line")),
            ("scatter", _("Scatter")),
            ("bar", _("Bar")),
        ]
    },
)

X_AXIS_LABEL_OPTION = OptionDefinition(
    "x_axis_label",
    _("X-axis label"),
    _("Overrides the X-axis label. Leave blank to show no custom axis title."),
    CharField,
)

X_AXIS_ORDER_OPTION = OptionDefinition(
    "x_axis_order",
    _("X-axis order"),
    _("Comma separated order for text X-axis values, for example Mon, Tue, Wed."),
    CharField,
    restrict_to=[TileFieldType.TEXT],
)

Y_AXIS_LABEL_OPTION = OptionDefinition(
    "y_axis_label",
    _("Y-axis label"),
    _("Overrides the Y-axis label. Leave blank to show no custom axis title."),
    CharField,
)

STACKED_OPTION = OptionDefinition(
    "stacked",
    _("Stacked"),
    _("Stacks multiple Y-axis series when supported by the selected chart type."),
    BooleanField,
)

SHOW_LEGEND_OPTION = OptionDefinition(
    "show_legend",
    _("Show legend"),
    _("Shows the legend when enabled. By default, legends are only shown for multiple series."),
    BooleanField,
)

LEGEND_POSITION_OPTION = OptionDefinition(
    "legend_position",
    _("Legend position"),
    _("Where the legend should be placed."),
    ChoiceField,
    {
        "choices": [
            ("right", _("Right")),
            ("top", _("Top")),
            ("bottom", _("Bottom")),
            ("left", _("Left")),
        ]
    },
)

AGGREGATOR_OPTION = OptionDefinition(
    "aggregator",
    "Aggregator",
    "How to aggregate the value",
    ChoiceField,
    {},
    choices_provider=get_aggregator_choices,
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
                icon="fa-solid fa-arrow-right",
                description=_("The field to be used for the X-axis of the chart."),
                allow_multiple=False,
                opts=[
                    LABEL_OPTION
                ]
            ),
            FieldDefinition(
                key="y_axis",
                label=_("Y-Axis"),
                icon="fa-solid fa-arrow-up",
                description=_("The field to be used for the Y-axis of the chart."),
                restrict_to=[TileFieldType.NUMERIC],
                opts=[
                    LABEL_OPTION,
                    COLOR_OPTION,
                ]
            ),
        ],
        opts=[
            CHART_TYPE_OPTION,
            X_AXIS_LABEL_OPTION,
            X_AXIS_ORDER_OPTION,
            Y_AXIS_LABEL_OPTION,
            STACKED_OPTION,
            SHOW_LEGEND_OPTION,
            LEGEND_POSITION_OPTION,
        ],
        render_cls=AnalyticsTwoDimChartRenderer,
    )

    TABLE = AnalyticsTileTypeDefinition(
        key="TABLE",
        name=str(_("Table")),
        description=str(_("Displays data from a custom query in a structured tabular format, enabling users to view, sort, and analyze information in rows and columns for easy comparison and reference.")),
        icon="fa-table",
        fields=[
            FieldDefinition(
                "columns",
                label=_("Columns"),
                icon="",
                description=_("The columns of the table"),
                opts=[
                    LABEL_OPTION,
                    PREFIX_OPTION,
                    SUFFIX_OPTION,
                    FORMATTER_OPTION,
                ]
            )
        ],
        opts=[
            SIZE_OPTION
        ],
        render_cls=AnalyticsTableRenderer
    )

    KPI = AnalyticsTileTypeDefinition(
        key="KPI",
        name=str(_("KPI")),
        description=str(_("Presents key performance indicators (KPIs) derived from a custom query in a concise and visually impactful format, allowing users to quickly assess critical metrics and track progress towards specific goals.")),
        icon="fa-tachometer-alt",
        fields=[
            FieldDefinition(
                key="value",
                label=_("Value"),
                icon="fa fa-hashtag",
                description=_("The primary value"),
                opts=[
                    FORMATTER_OPTION,
                    AGGREGATOR_OPTION,
                    PREFIX_OPTION,
                    SUFFIX_OPTION,
                ]
            ),
            FieldDefinition(
                key="sub_value",
                label=_("Sub Value"),
                icon="fa fa-hashtag",
                description=_("The secondary value that appears below the main value"),
                opts=[
                    FORMATTER_OPTION,
                    AGGREGATOR_OPTION,
                    PREFIX_OPTION,
                    SUFFIX_OPTION,
                ]
            )
        ],
        opts=[
            
        ],
        render_cls=AnalyticsKpiRenderer
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
    """Stores a selected query field together with its field-specific options."""

    name: str
    opts: Optional[dict] = None

class AnalyticsTileConfig(BaseTileConfig):
    """Session-backed configuration for an analytics tile being built."""

    query: str
    type: str  # Must be one of the supported types
    fields: Optional[dict[str, list[FieldConfig]]] = None
    opts: Optional[dict] = None

    @classmethod
    def get_default(cls, *args, **kwargs) -> Self:
        """
        Creates a default analytics tile.
        """
        query = kwargs.get("query")
        if query is None and args:
            query = args[0]

        return cls(
            query=query or "",
            type=AnalyticsTileType.KPI.value.key,
            fields=None,
            opts=None,
        )
    
    @classmethod
    def get_operation(cls, operation: str):
        """Returns the operation definition for an analytics builder action."""

        return {
            "set_type": TileOperationDefinition(
                SetTypeOperation,
                SetTypeHandler,
            ),
            "set_opts": TileOperationDefinition(
                SetOptsOperation,
                SetOptsHandler,
            ),
            "set_field_opts": TileOperationDefinition(
                SetFieldOptsOperation,
                SetFieldOptsHandler,
            ),
            "add_field": TileOperationDefinition(
                AddFieldOperation,
                AddFieldHandler,
            ),
            "remove_field": TileOperationDefinition(
                RemoveFieldOperation,
                RemoveFieldHandler,
            ),
        }[operation]

# -------------------------------
# State management
# -------------------------------

class SetTypeOperation(BaseModel):
    """Payload for switching the analytics tile type."""

    tile_type: str


class SetTypeHandler(TileOperationHandler):
    """Updates the selected analytics tile type without clearing configuration."""

    @staticmethod
    def handle(config: AnalyticsTileConfig, data: SetTypeOperation):
        AnalyticsTileType.from_key(data.tile_type)
        config.type = data.tile_type

        return TileOperationHandlerRespone(
            config,
            _("Tile type updated"),
        )


class SetOptsOperation(BaseModel):
    """Payload for updating global analytics tile options."""

    opts: dict[str, str]


class SetOptsHandler(TileOperationHandler):
    """Persists global analytics tile option values."""

    @staticmethod
    def handle(config: AnalyticsTileConfig, data: SetOptsOperation):
        config.opts = data.opts or None

        return TileOperationHandlerRespone(
            config,
            _("Options updated"),
        )


class SetFieldOptsOperation(BaseModel):
    """Payload for updating options on a selected analytics field."""

    field_id: str
    draggable_field_id: str
    opts: dict[str, str]


class SetFieldOptsHandler(TileOperationHandler):
    """Persists option values for one selected analytics field."""

    @staticmethod
    def handle(config: AnalyticsTileConfig, data: SetFieldOptsOperation):
        fields = dict(config.fields or {})
        existing_fields = list(fields.get(data.draggable_field_id) or [])

        for field in existing_fields:
            if field.name == data.field_id:
                field.opts = data.opts or None
                config.fields = fields
                return TileOperationHandlerRespone(
                    config,
                    _("Field options updated"),
                )

        return TileOperationHandlerRespone(
            config,
            _("Field does not exist"),
            "error",
        )

class AddFieldOperation(BaseModel):
    """Payload for attaching one output field to a tile field slot."""

    field_id: str
    draggable_field_id: str


class AddFieldHandler(TileOperationHandler):
    """Adds or replaces a selected output field on a tile field slot."""

    @staticmethod
    def handle(config: AnalyticsTileConfig, data: AddFieldOperation):
        fields = dict(config.fields or {})
        tile_type_definition = AnalyticsTileType.from_key(config.type)
        draggable_field_definition = next(
            (field for field in tile_type_definition.fields if field.key == data.draggable_field_id),
            None,
        )

        if draggable_field_definition is None:
            return TileOperationHandlerRespone(
                config,
                _("Field slot does not exist"),
                "error",
            )

        field_config = FieldConfig(
            name=data.field_id,
            opts={},
        )

        existing_fields = list(fields.get(data.draggable_field_id) or [])
        existing_fields = [field for field in existing_fields if field.name != data.field_id]

        if draggable_field_definition.allow_multiple:
            existing_fields.append(field_config)
            fields[data.draggable_field_id] = existing_fields
        else:
            fields[data.draggable_field_id] = [field_config]

        config.fields = fields

        return TileOperationHandlerRespone(
            config,
            _("Field updated"),
        )

class RemoveFieldOperation(BaseModel):
    """Payload for removing one selected output field from a tile field slot."""

    field_id: str
    draggable_field_id: str


class RemoveFieldHandler(TileOperationHandler):
    """Removes a selected output field from a tile field slot."""

    @staticmethod
    def handle(config: AnalyticsTileConfig, data: RemoveFieldOperation):
        fields = dict(config.fields or {})
        existing_fields = list(fields.get(data.draggable_field_id) or [])
        next_fields = [field for field in existing_fields if field.name != data.field_id]

        if next_fields:
            fields[data.draggable_field_id] = next_fields
        else:
            fields.pop(data.draggable_field_id, None)

        config.fields = fields or None

        return TileOperationHandlerRespone(
            config,
            _("Field removed"),
        )


# -------------------------------
# Utility functions
# -------------------------------

def options_form_factory(opts:list[OptionDefinition], field_type: TileFieldType | str | None = None) -> Type[Form]:
    """Builds a form class for global tile options."""

    return _build_options_form(opts, field_type=field_type)


def _build_options_form(opts: list[OptionDefinition], field_type: TileFieldType | str | None = None) -> Type[Form]:
    """Builds a form class for the provided option definitions and field type."""

    form_fields = {}
    primitive_field_type = None
    if field_type is not None:
        primitive_field_type = field_type if isinstance(field_type, TileFieldType) else to_primitive_field_type(field_type)

    for opt in opts:
        if opt.restrict_to and primitive_field_type not in opt.restrict_to:
            continue

        field_kwargs = dict(opt.field_args or {})
        if opt.choices_provider:
            field_kwargs["choices"] = opt.choices_provider(primitive_field_type)
        field_kwargs.setdefault("label", opt.label)
        field_kwargs.setdefault("help_text", opt.description)
        field_kwargs.setdefault("required", False)
        field_cls = ChoiceField if "choices" in field_kwargs else opt.field_cls
        form_fields[opt.key] = field_cls(**field_kwargs)

    return type("AnalyticsTileOptionsForm", (Form,), form_fields)


def get_field_options_form_factory(field_definition: FieldDefinition, field_type: str | None = None) -> Type[Form]:
    """Builds a form class for one field slot based on the selected output field type."""

    return _build_options_form(field_definition.opts, field_type=field_type)


def is_field_definition_allowed(field_definition: FieldDefinition, field_type: str | None = None) -> bool:
    """Checks whether an output field type is compatible with a tile field slot."""

    if field_definition.restrict_to is None:
        return True

    return to_primitive_field_type(field_type) in field_definition.restrict_to
    