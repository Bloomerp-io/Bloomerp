from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Self, Optional, Type

from django.forms import BooleanField, CharField, ChoiceField, Field, Form
from django.http import QueryDict
from django.utils.translation import gettext_lazy as _
from enum import Enum
from pydantic import BaseModel, Field as PydanticField, field_validator

from bloomerp.services.sql_services import DatabaseTable
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.workspaces.analytics_tile.kpi import AnalyticsKpiRenderer
from bloomerp.workspaces.analytics_tile.pie_chart import AnalyticsPieChartRenderer
from bloomerp.workspaces.analytics_tile.table import AnalyticsTableRenderer
from bloomerp.workspaces.analytics_tile.two_dim_chart import AnalyticsTwoDimChartRenderer
from bloomerp.workspaces.analytics_tile.utils import (
    TileFieldType,
    get_aggregator_choices,
    get_formatter_choices,
    to_primitive_field_type,
)
from bloomerp.workspaces.base import BaseTileConfig, TileOperationDefinition, TileOperationHandler, TileOperationHandlerRespone
from django import forms

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

PAGE_SIZE_OPTION = OptionDefinition(
    "page_size",
    _("Page Size"),
    _("The number of records on each page"),
    forms.ChoiceField,
    {
        "choices" : [
            (10,10),
            (25,25),
            (50,50)
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

FILTER_FIELD = FieldDefinition(
    key="filter",
    label=_("Filter"),
    icon="fa-solid fa-filter",
    description=_("Applicable filter on this field"),
    allow_multiple=True
)

ADVANCED_FORMATTER_OPTION = OptionDefinition(
    "advanced_formatting",
    _("Advanced formatting"),
    _("HTML based formatting. The value is injected as {{ value }}, the pre-formatted value as {{ pre_formatted_value }}."),
    field_cls=forms.CharField,
    field_args={
        "widget" : CodeEditorWidget(language="html", launch_from_button=True)
    }
)

ADVANCED_FORMATTER_OPTION_VALUE = copy.copy(ADVANCED_FORMATTER_OPTION)
ADVANCED_FORMATTER_OPTION_VALUE.key = "advanced_formatting_value"
ADVANCED_FORMATTER_OPTION_VALUE.label = "Advanced formatting (value)"
ADVANCED_FORMATTER_OPTION_VALUE.description = "HTML based formatting. Values are injected as {{ var_col_name }} and {{ preformatted_var_col_name }}."

ADVANCED_FORMATTER_OPTION_SUB_VALUE = copy.copy(ADVANCED_FORMATTER_OPTION)
ADVANCED_FORMATTER_OPTION_SUB_VALUE.key = "advanced_formatting_sub_value"
ADVANCED_FORMATTER_OPTION_SUB_VALUE.label = "Advanced formatting (sub-value)"
ADVANCED_FORMATTER_OPTION_SUB_VALUE.description = "HTML based formatting. Values are injected as {{ var_col_name }} and {{ preformatted_var_col_name }}."



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
                    ADVANCED_FORMATTER_OPTION,
                ]
            ),
        ],
        opts=[
            SIZE_OPTION,
            PAGE_SIZE_OPTION
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
            ADVANCED_FORMATTER_OPTION_VALUE,
            ADVANCED_FORMATTER_OPTION_SUB_VALUE,    
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
        fields=[
            FieldDefinition(
                key="labels",
                label=_("Labels"),
                icon="fa-solid fa-tag",
                description=_("The field used for the pie slice labels."),
                allow_multiple=False,
                opts=[
                    LABEL_OPTION,
                ],
            ),
            FieldDefinition(
                key="values",
                label=_("Values"),
                icon="fa-solid fa-chart-pie",
                description=_("The numeric field used for the pie slice values."),
                allow_multiple=False,
                restrict_to=[TileFieldType.NUMERIC],
                opts=[
                    LABEL_OPTION,
                    FORMATTER_OPTION,
                    PREFIX_OPTION,
                    SUFFIX_OPTION,
                ],
            ),
        ],
        opts=[
            SHOW_LEGEND_OPTION,
            LEGEND_POSITION_OPTION,
        ],
        render_cls=AnalyticsPieChartRenderer,
    )

    @classmethod
    def from_key(cls, key: str) -> "AnalyticsTileTypeDefinition":
        for item in cls:
            if item.value.key == key:
                return item.value
        raise ValueError(f"Unsupported analytics tile type: {key}")

class AnalyticsTileFilter(BaseModel):
    field:str
    type:str 
    shared_key:Optional[str] = None

    @field_validator("shared_key")
    @classmethod
    def normalize_shared_key(cls, value):
        value = value.strip() if value else None
        if value and ":" in value:
            raise ValueError("Shared keys cannot contain :")
        return value or None
    

# Todo: make sure the field config is integrated with 
class FieldConfig(BaseModel):
    """Stores a selected query field together with its field-specific options."""

    name: str
    opts: dict = PydanticField(default_factory=dict)

class AnalyticsTileConfig(BaseTileConfig):
    """Session-backed configuration for an analytics tile being built."""

    query: str
    type: str  # Must be one of the supported types
    fields: dict[str, list[FieldConfig]] = PydanticField(default_factory=dict)
    opts: dict = PydanticField(default_factory=dict)
    filters: list[AnalyticsTileFilter] = PydanticField(default_factory=list)

    def get_filter_shared_key(self, name):
        configured = next((item for item in self.filters if item.field == name), None)
        return configured.shared_key if configured and configured.shared_key else super().get_filter_shared_key(name)

    @field_validator("filters", mode="before")
    @classmethod
    def normalize_filters(cls, value):
        """Accept legacy field-keyed schemas while storing filters as a list."""
        if value is None:
            return []
        if isinstance(value, dict):
            return list(value.values())
        return value

    @field_validator("filters")
    @classmethod
    def validate_unique_filter_fields(
        cls,
        value: list[AnalyticsTileFilter],
    ) -> list[AnalyticsTileFilter]:
        fields = [filter_config.field for filter_config in value]
        if len(fields) != len(set(fields)):
            raise ValueError("Analytics tile filter fields must be unique.")
        return value
    
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
            fields={},
            opts={},
            filters=[],
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
            "add_filter": TileOperationDefinition(
                AddFilterOperation,
                AddFilterHandler,
            ),
            "set_filter_shared_key": TileOperationDefinition(
                SetFilterSharedKeyOperation, SetFilterSharedKeyHandler,
            ),
            "remove_filter": TileOperationDefinition(
                RemoveFilterOperation,
                RemoveFilterHandler,
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
        config.opts = data.opts or {}

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
                field.opts = data.opts or {}
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

        config.fields = fields

        return TileOperationHandlerRespone(
            config,
            _("Field removed"),
        )

# Filters
class AddFilterOperation(BaseModel):
    """Payload for adding a filter to the analytics tile."""
    field:str
    type:str
    
class AddFilterHandler(TileOperationHandler):
    """Adds a filter to the analytics tile."""

    @staticmethod
    def handle(config: AnalyticsTileConfig, data: AddFilterOperation):
        filters = list(config.filters or [])
        if any(filter_config.field == data.field for filter_config in filters):
            return TileOperationHandlerRespone(
                config,
                _("Filter already exists"),
                "warning"
            )
        
        filters.append(
            AnalyticsTileFilter(
                field=data.field,
                type=data.type,
            )
        )
        config.filters = filters

        return TileOperationHandlerRespone(
            config,
            _("Filter added"),
        )

class SetFilterSharedKeyOperation(BaseModel):
    field: str
    shared_key: str | None = None


class SetFilterSharedKeyHandler(TileOperationHandler):
    @staticmethod
    def handle(config: AnalyticsTileConfig, data: SetFilterSharedKeyOperation):
        for field in config.filters:
            if field.field == data.field:
                validated = AnalyticsTileFilter.model_validate({**field.model_dump(), "shared_key": data.shared_key})
                field.shared_key = validated.shared_key
                return TileOperationHandlerRespone(config, _("Shared key updated"))
        raise ValueError("Unknown filter field")


class RemoveFilterOperation(BaseModel):
    """Payload for removing a filter from the analytics tile."""

    field:str
        
class RemoveFilterHandler(TileOperationHandler):
    """Removes a filter from the analytics tile."""

    @staticmethod
    def handle(config: AnalyticsTileConfig, data: RemoveFilterOperation):
        config.filters = [
            filter_config
            for filter_config in config.filters
            if filter_config.field != data.field
        ]

        return TileOperationHandlerRespone(
            config,
            _("Filter removed"),
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
    
    
def get_filters_from_query(table: DatabaseTable, query: str):
    """Expose only result columns as filter candidates."""
    return [
        {"field": field.name,
         "type": to_primitive_field_type(field.field_type).value.key,
         "icon": to_primitive_field_type(field.field_type).value.icon}
        for field in table.fields
    ]


def _lookup_sql_literal(value, *, dialect="postgresql") -> str:
    """Render a compiled lookup parameter for the active database text API."""
    from datetime import date, datetime, time
    from decimal import Decimal
    from math import isfinite

    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        if not isfinite(value):
            raise ValueError("Non-finite SQL filter value")
        return str(value)
    if isinstance(value, (date, datetime, time)):
        value = value.isoformat()
    text = str(value)
    if "\x00" in text:
        raise ValueError("SQL filter values cannot contain NUL")
    escaped = text.replace("'", "''")
    if dialect == "postgresql":
        return "E'" + escaped.replace("\\", "\\\\") + "'"
    return "'" + escaped + "'"


def get_filtered_query(config: AnalyticsTileConfig, params: QueryDict, *, resolver=None, tile_id=None, request=None) -> str:
    """Apply canonical filters to configured columns, retaining tile-local AND/OR.

    A workspace resolver maps shared identities to this tile.
    """
    from django.core.exceptions import ValidationError
    from django.db import connection
    from bloomerp.filters.compiler import compile_sql_field_filters
    from bloomerp.filters.parser import deserialize_filters, parse_shorthand_filters
    from bloomerp.filters.resolver import FilterFieldResolver, filters_for_tile
    from bloomerp.workspaces.analytics_tile.utils import analytics_tile_filter_field_factory

    local = FilterFieldResolver.for_fields(analytics_tile_filter_field_factory(config))
    tile_id = str(tile_id or params.get("tile_id") or "")
    if resolver is None and request is not None and params.get("workspace_id"):
        resolver = FilterFieldResolver.for_user("workspace", params["workspace_id"], request.user)

    query = _strip_trailing_query_semicolon(config.query)
    groups = []
    entries = params.lists() if hasattr(params, "lists") else ((key, [value]) for key, value in params.items())
    for key, values in entries:
        for value in values:
            if key == "filter":
                projected = filters_for_tile(deserialize_filters(value), tile_id=tile_id, resolver=resolver)
                for group in projected:
                    for condition in group.conditions:
                        local.resolve(condition.field_path)
                groups.extend(projected)
                continue
            # Legacy workspace parameters may belong to another tile. Only
            # recognized local shorthand is retained; canonical JSON is strict.
            try:
                groups.extend(parse_shorthand_filters({key: value}, resolver=local))
            except ValidationError:
                continue

    if not groups:
        return query
    compiled = compile_sql_field_filters(groups, resolver=local)
    # SqlExecutor currently takes SQL text. Adapt bound parameters only here,
    # after shared compilation; lookup factories remain parameterized.
    fragments = compiled.clause.split("%s")
    if len(fragments) != len(compiled.parameters) + 1:
        raise ValueError("SQL lookup parameter count mismatch")
    clause = fragments[0]
    for parameter, fragment in zip(compiled.parameters, fragments[1:]):
        clause += _lookup_sql_literal(parameter, dialect=connection.vendor) + fragment
    return f"SELECT * FROM ({query}) AS filtered_query WHERE {clause}"


def _strip_trailing_query_semicolon(query: str) -> str:
    return query.strip().rstrip(";").strip()
