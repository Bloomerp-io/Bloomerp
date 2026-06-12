from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable

import calendar
from django import forms
import django_filters

from enum import Enum
from functools import partial

from typing import Optional
from typing import TYPE_CHECKING

from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField

# ---------------------
# Helper functions
# ---------------------

def _is_truthy_lookup_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"

    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    value_str = str(value).strip()
    if value_str.lower() in {"true", "false"}:
        return value_str.upper()

    try:
        float(value_str)
    except (TypeError, ValueError):
        escaped_value = value_str.replace("'", "''")
        return f"'{escaped_value}'"

    return value_str


def _sql_like_value(value: Any, *, prefix: str = "", suffix: str = "") -> str:
    escaped_value = str(value).strip().replace("'", "''")
    return f"'{prefix}{escaped_value}{suffix}'"


def _sql_in_values(value: Any) -> str:
    values = value
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",")]
    elif not isinstance(value, (list, tuple, set)):
        values = [value]

    rendered_values = ", ".join(_sql_literal(item) for item in values if str(item).strip() != "")
    return f"IN ({rendered_values})"


def _sql_is_null(value: Any) -> str:
    return "IS NULL" if _is_truthy_lookup_value(value) else "IS NOT NULL"

# ---------------------
# Widget functions
# ---------------------
def _equals_widget(application_field: "ApplicationField") -> forms.Widget:
    from bloomerp.field_types.types import FieldType
    match application_field.field_type_enum:
        case FieldType.BOOLEAN_FIELD:
            return forms.Select(choices=[("true", "True"), ("false", "False")], attrs={"class": "select w-full"})
        case FieldType.FOREIGN_KEY:
            return ForeignFieldWidget(model=application_field.related_model.model_class(), attrs={"class": "input w-full"})
        case FieldType.MANY_TO_MANY_FIELD:
            return ForeignFieldWidget(model=application_field.related_model.model_class(), attrs={"class": "input w-full", "is_m2m": True})
        case FieldType.DATE_FIELD:
            return forms.DateInput(attrs={"class": "input w-full", "type": "date"})
        case FieldType.DATE_TIME_FIELD:
            return forms.DateTimeInput(attrs={"class": "input w-full", "type": "datetime-local"})
        case _:
            return forms.TextInput(attrs={"class": "input w-full"})

def _in_widget(application_field: "ApplicationField") -> forms.Widget:
    from bloomerp.field_types.types import FieldType
    match application_field.field_type_enum:
        case FieldType.FOREIGN_KEY | FieldType.MANY_TO_MANY_FIELD:
            return ForeignFieldWidget(model=application_field.related_model.model_class(), attrs={"class": "input w-full", "is_m2m":True})
        case _:
            return forms.TextInput(attrs={"class": "input w-full", "placeholder": "Enter comma-separated values"})

def _hidden_true(application_field: "ApplicationField") -> forms.Widget:
    return forms.HiddenInput(attrs={"value": "true"})

# ---------------------
# Defintion
# ---------------------
@dataclass
class LookupDefinition:
    id: str
    display_name: str
    django_representation: str  # The Django ORM lookup (e.g., "icontains", "gte")
    description: Optional[str] = None

    # Filter configuration for django-filters
    filter_class: Optional[type] = None  # e.g., django_filters.CharFilter
    aliases: list[str] = dataclass_field(default_factory=list)  # Alternative field name patterns: ["", "__exact", "__equals"]

    # For special filter configurations (e.g., ModelMultipleChoiceFilter needs queryset)
    get_filter_kwargs: Optional[Callable[[Any], dict]] = None  # Function that returns extra kwargs  

    # SQL
    sql_operator: Callable[[Any], str] = lambda value: f"= {_sql_literal(value)}"
    
    def render(self, application_field, name_override: Optional[str] = None) -> str:
        return self.widget_func(application_field).render(
            name=name_override or application_field.field,
            value=None,
        )

    # Widget function
    widget_func: Optional[Callable[["ApplicationField"], forms.Widget]] = lambda application_field: forms.TextInput(attrs={"class": "input w-full"})
    
class Lookup(Enum):
    EQUALS = LookupDefinition(
        id="equals",
        display_name="Equals",
        django_representation="exact",
        aliases=["", "__exact", "__equals"],  # Can use field_name, field_name__exact, or field_name__equals
        filter_class=django_filters.CharFilter,
        sql_operator=lambda value: f"= {_sql_literal(value)}",
        widget_func=_equals_widget
    )
    
    IEXACT = LookupDefinition(
        id="iexact",
        display_name="Equals (case-insensitive)",
        django_representation="iexact",
        aliases=["__iexact"],
        description="Case-insensitive exact match.",
        sql_operator=lambda value: f"LIKE {_sql_literal(value)}",
        widget_func=_equals_widget
    )

    CONTAINS = LookupDefinition(
        id="contains",
        display_name="Contains",
        django_representation="icontains",
        aliases=["__icontains", "__contains"],
        description="Containment test (generated as icontains by default).",
        sql_operator=lambda value: f"LIKE {_sql_like_value(value, prefix='%', suffix='%')}",
        widget_func=_equals_widget
    )

    STARTS_WITH = LookupDefinition(
        id="starts_with",
        display_name="Starts With",
        django_representation="startswith",
        aliases=["__startswith", "__istartswith"],
        description="Starts with test.",
        sql_operator=lambda value: f"LIKE {_sql_like_value(value, suffix='%')}",
        widget_func=_equals_widget
    )

    ENDS_WITH = LookupDefinition(
        id="ends_with",
        display_name="Ends With",
        django_representation="endswith",
        aliases=["__endswith", "__iendswith"],
        description="Ends with test.",
        sql_operator=lambda value: f"LIKE {_sql_like_value(value, prefix='%')}",
        widget_func=_equals_widget
    )

    GREATER_THAN = LookupDefinition(
        id="greater_than",
        display_name="Greater Than",
        django_representation="gt",
        aliases=["__gt"],
        sql_operator=lambda value: f"> {_sql_literal(value)}",
        widget_func=_equals_widget
    )

    GREATER_THAN_OR_EQUAL = LookupDefinition(
        id="greater_than_or_equal",
        display_name="Greater Than or Equal",
        django_representation="gte",
        aliases=["__gte"],
        sql_operator=lambda value: f">= {_sql_literal(value)}",
        widget_func=_equals_widget
    )

    LESS_THAN = LookupDefinition(
        id="less_than",
        display_name="Less Than",
        django_representation="lt",
        aliases=["__lt"],
        sql_operator=lambda value: f"< {_sql_literal(value)}",
        widget_func=_equals_widget
    )

    LESS_THAN_OR_EQUAL = LookupDefinition(
        id="less_than_or_equal",
        display_name="Less Than or Equal",
        django_representation="lte",
        aliases=["__lte"],
        sql_operator=lambda value: f"<= {_sql_literal(value)}",
        widget_func=_equals_widget
    )

    IN = LookupDefinition(
        id="in",
        display_name="In",
        django_representation="in",
        aliases=["__in"],
        description="Checks if value is in a list of values.",
        sql_operator=_sql_in_values,
        widget_func=_in_widget
    )

    IS_NULL = LookupDefinition(
        id="is_null",
        display_name="Is Null",
        django_representation="isnull",
        aliases=["__isnull"],
        description="Checks if value is null (True) or not null (False).",
        sql_operator=_sql_is_null,
        widget_func=lambda application_field: forms.Select(choices=[("true", "True"), ("false", "False")], attrs={"class": "select w-full"})
    )

    NOT_EQUALS = LookupDefinition(
        id="not_equals",
        display_name="Not Equals",
        django_representation="ne",
        aliases=["__ne", "__not_equals"],
        description="Not equal comparison.",
        sql_operator=lambda value: f"!= {_sql_literal(value)}",
        widget_func=_equals_widget
    )

    EQUALS_USER = LookupDefinition(
        id="equals_user",
        display_name="Equals Current User",
        django_representation="",
        widget_func=lambda x: forms.HiddenInput(attrs={"value": "$user"})
    )

    FOREIGN_ADVANCED = LookupDefinition(
        id="foreign_advanced",
        display_name="Advanced Lookup",
        django_representation="",
        
    )

    TODAY = LookupDefinition(
        id="today",
        display_name="Today",
        django_representation="today",
        aliases=["__today"],
        widget_func=_hidden_true
        
    )

    YESTERDAY = LookupDefinition(
        id="yesterday",
        display_name="Yesterday",
        django_representation="yesterday",
        aliases=["__yesterday"],
        widget_func=_hidden_true
    )

    THIS_WEEK = LookupDefinition(
        id="this_week",
        display_name="This Week",
        django_representation="this_week",
        aliases=["__this_week"],
        widget_func=_hidden_true
    )

    LAST_WEEK = LookupDefinition(
        id="last_week",
        display_name="Last Week",
        django_representation="last_week",
        aliases=["__last_week"],
        widget_func=_hidden_true
    )

    THIS_MONTH = LookupDefinition(
        id="this_month",
        display_name="This Month",
        django_representation="this_month",
        aliases=["__this_month"],
        widget_func=_hidden_true
    )

    LAST_MONTH = LookupDefinition(
        id="last_month",
        display_name="Last Month",
        django_representation="last_month",
        aliases=["__last_month"],
        widget_func=_hidden_true
    )

    THIS_QUARTER = LookupDefinition(
        id="this_quarter",
        display_name="This Quarter",
        django_representation="this_quarter",
        aliases=["__this_quarter"],
        widget_func=_hidden_true,
    )

    LAST_QUARTER = LookupDefinition(
        id="last_quarter",
        display_name="Last Quarter",
        django_representation="last_quarter",
        aliases=["__last_quarter"],
        widget_func=_hidden_true,
    )

    THIS_YEAR = LookupDefinition(
        id="this_year",
        display_name="This Year",
        django_representation="this_year",
        aliases=["__this_year"],
        widget_func=_hidden_true,
    )

    LAST_YEAR = LookupDefinition(
        id="last_year",
        display_name="Last Year",
        django_representation="last_year",
        aliases=["__last_year"],
        widget_func=_hidden_true
    )

    YEAR = LookupDefinition(
        id="year",
        display_name="Year",
        django_representation="year",
        aliases=["__year"],
        widget_func=lambda x: forms.NumberInput(attrs={"class": "input w-full", "min": 1, "max": 9999, "type": "number"})
    )

    MONTH = LookupDefinition(
        id="month",
        display_name="Month",
        django_representation="month",
        aliases=["__month"],
        widget_func=lambda x: forms.NumberInput(attrs={"class": "input w-full", "min": 1, "max": 12, "type": "number"})
    )

    DAY = LookupDefinition(
        id="day",
        display_name="Day",
        django_representation="day",
        aliases=["__day"],
        widget_func=lambda x: forms.NumberInput(attrs={"class": "input w-full", "min": 1, "max": 31, "type": "number"})
    )

    WEEK = LookupDefinition(
        id="week",
        display_name="Week",
        django_representation="week",
        aliases=["__week"],
        widget_func=lambda application_field: forms.NumberInput(attrs={"class": "input w-full", "min": 1, "max": 53, "type": "number"})
    )
    DAY_OF_WEEK = LookupDefinition(
        id="day_of_week",
        display_name="Day of Week",
        django_representation="day_of_week",
        aliases=["__day_of_week"],
        widget_func=lambda application_field: forms.Select(choices=[(str(i), calendar.day_name[i-1]) for i in range(1,8)], attrs={"class": "select w-full"})
    )
    DAY_OF_WEEK_IN = LookupDefinition(
        id="day_of_week_in",
        display_name="Day of Week In",
        django_representation="day_of_week_in",
        aliases=["__day_of_week_in"],
        widget_func=lambda application_field: forms.SelectMultiple(choices=[(str(i), calendar.day_name[i-1]) for i in range(1,8)], attrs={"class": "select w-full"})
    )

DATE_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.GREATER_THAN,
    Lookup.GREATER_THAN_OR_EQUAL,
    Lookup.LESS_THAN,
    Lookup.LESS_THAN_OR_EQUAL,
    Lookup.TODAY,
    Lookup.YESTERDAY,
    Lookup.THIS_WEEK,
    Lookup.LAST_WEEK,
    Lookup.THIS_MONTH,
    Lookup.LAST_MONTH,
    Lookup.THIS_QUARTER,
    Lookup.LAST_QUARTER,
    Lookup.THIS_YEAR,
    Lookup.LAST_YEAR,
    Lookup.YEAR,
    Lookup.MONTH,
    Lookup.DAY,
    Lookup.WEEK,
    Lookup.IS_NULL,
    Lookup.NOT_EQUALS,
    Lookup.DAY_OF_WEEK,
    Lookup.DAY_OF_WEEK_IN,
]

WEEK_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.GREATER_THAN,
    Lookup.GREATER_THAN_OR_EQUAL,
    Lookup.LESS_THAN,
    Lookup.LESS_THAN_OR_EQUAL,
    Lookup.YEAR,
    Lookup.WEEK,
    Lookup.IS_NULL,
    Lookup.NOT_EQUALS,
]

BOOLEAN_LOOKUPS = [
    Lookup.EQUALS,
]

NUMERIC_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.GREATER_THAN,
    Lookup.GREATER_THAN_OR_EQUAL,
    Lookup.LESS_THAN,
    Lookup.LESS_THAN_OR_EQUAL,
    Lookup.IN,
    Lookup.IS_NULL,
    Lookup.NOT_EQUALS,
]

TEXT_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.IEXACT,
    Lookup.CONTAINS,
    Lookup.STARTS_WITH,
    Lookup.ENDS_WITH,
    Lookup.IN,
    Lookup.IS_NULL,
    Lookup.NOT_EQUALS,
]

