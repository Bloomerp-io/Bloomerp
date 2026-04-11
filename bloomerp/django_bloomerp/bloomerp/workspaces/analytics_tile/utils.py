from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional


@dataclass
class TileFieldTypeDefinition:
    """Describes one primitive analytics field type used by the builder."""

    key: str
    name: str
    icon: str

class TileFieldType(Enum):
    """Primitive field types used to keep analytics options consistent."""

    NUMERIC = TileFieldTypeDefinition("numeric", "Numeric", "fa-solid fa-hashtag")
    TEXT = TileFieldTypeDefinition("text", "Text", "fa-solid fa-font")
    DATE = TileFieldTypeDefinition("date", "Date", "fa-solid fa-calendar-day")
    BOOL = TileFieldTypeDefinition("bool", "Boolean", "fa-solid fa-toggle-on")
    DATETIME = TileFieldTypeDefinition("datetime", "Date & Time", "fa-solid fa-clock")

def to_primitive_field_type(field_type: str | None) -> TileFieldType:
    """Maps a database or Python-like type string to a primitive analytics type."""
    normalized = (field_type or "").strip().lower()

    if not normalized:
        return TileFieldType.TEXT

    if "bool" in normalized:
        return TileFieldType.BOOL

    if "datetime" in normalized or "timestamp" in normalized:
        return TileFieldType.DATETIME

    if normalized == "date" or ("date" in normalized and "time" not in normalized):
        return TileFieldType.DATE

    if "time" in normalized:
        return TileFieldType.DATETIME

    if any(token in normalized for token in ("int", "decimal", "float", "double", "number", "numeric", "real")):
        return TileFieldType.NUMERIC

    return TileFieldType.TEXT


def get_primitive_field_type_definition(field_type: TileFieldType | str | None = None) -> TileFieldTypeDefinition:
    """Returns the primitive field type definition for a given field type value."""

    primitive_type = field_type if isinstance(field_type, TileFieldType) else to_primitive_field_type(field_type)
    return primitive_type.value


def get_primitive_field_icon(field_type: TileFieldType | str | None = None) -> str:
    """Returns the icon for a primitive field type."""

    return get_primitive_field_type_definition(field_type).icon


# ----------------------
# Aggregators
# ----------------------
@dataclass
class AggregatorDefinition:
    """Describes one aggregation option and the primitive types it supports."""

    name: str
    func: Callable[[Any], Any]
    restrict_to: Optional[list[TileFieldType]] = None

class Aggregator(Enum):
    """Supported aggregations for analytics field configuration."""
    FIRST = AggregatorDefinition(
        "First",
        lambda values: values.iloc[0] if len(values) > 0 else None,
    )
    LAST = AggregatorDefinition(
        "Last",
        lambda values: values.iloc[-1] if len(values) > 0 else None,
    )
    SUM = AggregatorDefinition(
        "Sum",
        lambda values: values.sum(),
        [TileFieldType.NUMERIC],
    )
    AVG = AggregatorDefinition(
        "Average",
        lambda values: values.mean(),
        [TileFieldType.NUMERIC],
    )
    COUNT = AggregatorDefinition(
        "Count",
        lambda values: values.count(),
    )
    


# ----------------------
# Formatters
# ----------------------

@dataclass
class FormatterDefinition:
    """Describes one formatter option and the primitive types it supports."""

    name: str
    func: Callable[[Any], Any]
    restrict_to: Optional[list[TileFieldType]] = None

class Formatter(Enum):
    """Supported display formatters for analytics field configuration."""

    NONE = FormatterDefinition(
        "None",
        lambda value: value,
    )

    UPPER_CASE = FormatterDefinition(
        "Upper case",
        lambda value: value.upper() if isinstance(value, str) else value,
        [TileFieldType.TEXT]
    )
    LOWER_CASE = FormatterDefinition(
        "Lower case",
        lambda value: value.lower() if isinstance(value, str) else value,
        [TileFieldType.TEXT],
    )
    STRIP = FormatterDefinition(
        "Strip",
        lambda value: value.strip() if isinstance(value, str) else value,
        [TileFieldType.TEXT],
    )
    CURRENCY_USD = FormatterDefinition(
        "Currency (USD)",
        lambda value: f"${value:,.2f}" if value is not None else value,
        [TileFieldType.NUMERIC],
    )
    INTEGER = FormatterDefinition(
        "Integer",
        lambda value: f"{int(round(value))}" if value is not None else value,
        [TileFieldType.NUMERIC],
    )
    # TODO: In the future, locale-specific double formatting should use the user's preference.
    DOUBLE_US = FormatterDefinition(
        "Double (US)",
        lambda value: f"{value:,.2f}" if value is not None else value,
        [TileFieldType.NUMERIC],
    )
    DOUBLE_EU = FormatterDefinition(
        "Double (EU)",
        lambda value: format(value, ",.2f").replace(",", "#").replace(".", ",").replace("#", ".") if value is not None else value,
        [TileFieldType.NUMERIC],
    )
    SCIENTIFIC = FormatterDefinition(
        "Scientific",
        lambda value: f"{value:.2e}" if value is not None else value,
        [TileFieldType.NUMERIC],
    )
    COMMA_SEPARATED = FormatterDefinition(
        "Comma separated",
        lambda value: f"{value:,}" if value is not None else value,
        [TileFieldType.NUMERIC],
    )
    PERCENTAGE = FormatterDefinition(
        "Percentage",
        lambda value: f"{value:.2%}" if value is not None else value,
        [TileFieldType.NUMERIC],
    )


def get_aggregator_choices(field_type: TileFieldType | str | None = None) -> list[tuple[str, str]]:
    """Returns aggregator choices filtered to the given primitive field type."""

    primitive_type = field_type if isinstance(field_type, TileFieldType) else to_primitive_field_type(field_type)
    return [
        (aggregator.name, aggregator.value.name)
        for aggregator in Aggregator
        if aggregator.value.restrict_to is None or primitive_type in aggregator.value.restrict_to
    ]


def get_formatter_choices(field_type: TileFieldType | str | None = None) -> list[tuple[str, str]]:
    """Returns formatter choices filtered to the given primitive field type."""

    primitive_type = field_type if isinstance(field_type, TileFieldType) else to_primitive_field_type(field_type)
    return [
        (formatter.name, formatter.value.name)
        for formatter in Formatter
        if formatter.value.restrict_to is None or primitive_type in formatter.value.restrict_to
    ]
