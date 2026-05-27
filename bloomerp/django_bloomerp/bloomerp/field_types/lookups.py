from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable

import calendar
from django import forms
import django_filters

from enum import Enum
from functools import partial

from typing import Optional
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField

# ---------------------
# Helper functions
# ---------------------

def render_month_lookup_value(
    application_field: "ApplicationField",
    name_override: Optional[str] = None,
) -> str:
    field_name = name_override or application_field.field
    return forms.Select(
        choices=[(str(index), calendar.month_name[index]) for index in range(1, 13)],
        attrs={"class": "select w-full"},
    ).render(name=field_name, value=None)


def render_numeric_lookup_value(
    application_field: "ApplicationField",
    name_override: Optional[str] = None,
    min_value: int | None = None,
    max_value: int | None = None,
) -> str:
    field_name = name_override or application_field.field
    attrs = {"class": "input w-full"}
    if min_value is not None:
        attrs["min"] = min_value
    if max_value is not None:
        attrs["max"] = max_value
    return forms.NumberInput(attrs=attrs).render(name=field_name, value=None)


def render_hidden_lookup_value(
    application_field: "ApplicationField",
    name_override: Optional[str] = None,
    value: str = "true",
    helper_text: str = "This filter uses the current date automatically.",
) -> str:
    field_name = name_override or application_field.field
    return (
        f'<input type="hidden" name="{field_name}" value="{value}">'
        f'<div class="input w-full">{helper_text}</div>'
    )


def render_advanced_lookup(application_field:"ApplicationField", name_override: Optional[str] = None) -> str:
    from bloomerp.models import ApplicationField
    from django.contrib.contenttypes.models import ContentType

    related_model = application_field.related_model

    objects = ApplicationField.objects.filter(
        content_type=ContentType.objects.get_for_model(related_model)
    )

    html = "<select class='select'>"
    for obj in objects:
        html += f"<option value='{obj.id}'>{obj.title}</option>"

    html += "</select>"

    return html


def render_equals_current_user(application_field:"ApplicationField", name_override: Optional[str] = None) -> str:
    field_name = name_override or application_field.field
    return forms.CharField().widget.render(
        name=field_name,
        value="$user",
        attrs={
            "class" : "input w-full",
            "disabled" : True
        }
    )


def render_foreign_key_field(application_field:"ApplicationField", name_override: Optional[str] = None) -> str:
    from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

    field_name = name_override or application_field.field
    widget_attrs = {}
    widget_attrs.update(application_field.meta or {})
    return ForeignFieldWidget(attrs=widget_attrs).render(
        name=field_name,
        value=None,
        attrs={
            "class": "input w-full"
        }
    )
    
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
    render_func : Optional[Callable] = None

    def render(self, application_field, name_override: Optional[str] = None) -> str:
        if not self.render_func:
            field_name = name_override or application_field.field
            return f"""<input type=\"text\" class=\"input w-full\" name=\"{field_name}\">"""

        return self.render_func(application_field, name_override=name_override)


class Lookup(Enum):
    EQUALS = LookupDefinition(
        id="equals",
        display_name="Equals",
        django_representation="exact",
        aliases=["", "__exact", "__equals"],  # Can use field_name, field_name__exact, or field_name__equals
        filter_class=django_filters.CharFilter
    )

    IEXACT = LookupDefinition(
        id="iexact",
        display_name="Equals (case-insensitive)",
        django_representation="iexact",
        aliases=["__iexact"],
        description="Case-insensitive exact match."
    )

    CONTAINS = LookupDefinition(
        id="contains",
        display_name="Contains",
        django_representation="icontains",
        aliases=["__icontains", "__contains"],
        description="Containment test (generated as icontains by default)."
    )

    STARTS_WITH = LookupDefinition(
        id="starts_with",
        display_name="Starts With",
        django_representation="startswith",
        aliases=["__startswith", "__istartswith"],
        description="Starts with test."
    )

    ENDS_WITH = LookupDefinition(
        id="ends_with",
        display_name="Ends With",
        django_representation="endswith",
        aliases=["__endswith", "__iendswith"],
        description="Ends with test."
    )

    GREATER_THAN = LookupDefinition(
        id="greater_than",
        display_name="Greater Than",
        django_representation="gt",
        aliases=["__gt"]
    )

    GREATER_THAN_OR_EQUAL = LookupDefinition(
        id="greater_than_or_equal",
        display_name="Greater Than or Equal",
        django_representation="gte",
        aliases=["__gte"]
    )

    LESS_THAN = LookupDefinition(
        id="less_than",
        display_name="Less Than",
        django_representation="lt",
        aliases=["__lt"]
    )

    LESS_THAN_OR_EQUAL = LookupDefinition(
        id="less_than_or_equal",
        display_name="Less Than or Equal",
        django_representation="lte",
        aliases=["__lte"]
    )

    IN = LookupDefinition(
        id="in",
        display_name="In",
        django_representation="in",
        aliases=["__in"],
        description="Checks if value is in a list of values."
    )

    IS_NULL = LookupDefinition(
        id="is_null",
        display_name="Is Null",
        django_representation="isnull",
        aliases=["__isnull"],
        description="Checks if value is null (True) or not null (False)."
    )

    NOT_EQUALS = LookupDefinition(
        id="not_equals",
        display_name="Not Equals",
        django_representation="ne",
        description="Not equal comparison."
    )

    EQUALS_USER = LookupDefinition(
        id="equals_user",
        display_name="Equals Current User",
        django_representation="",
        render_func=render_equals_current_user
    )

    FOREIGN_EQUALS = LookupDefinition(
        id="foreign_equals",
        display_name="Equals",
        django_representation="exact",
        render_func=render_foreign_key_field
    )

    FOREIGN_IN = LookupDefinition(
        id="foreign_in",
        display_name="In",
        django_representation="in",
        render_func=render_foreign_key_field
    )

    FOREIGN_ADVANCED = LookupDefinition(
        id="foreign_advanced",
        display_name="Advanced Lookup",
        django_representation="",
        render_func=render_advanced_lookup
    )

    TODAY = LookupDefinition(
        id="today",
        display_name="Today",
        django_representation="today",
        aliases=["__today"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses today's date automatically.",
        ),
    )

    YESTERDAY = LookupDefinition(
        id="yesterday",
        display_name="Yesterday",
        django_representation="yesterday",
        aliases=["__yesterday"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses yesterday's date automatically.",
        ),
    )

    THIS_WEEK = LookupDefinition(
        id="this_week",
        display_name="This Week",
        django_representation="this_week",
        aliases=["__this_week"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the current week automatically.",
        ),
    )

    LAST_WEEK = LookupDefinition(
        id="last_week",
        display_name="Last Week",
        django_representation="last_week",
        aliases=["__last_week"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the previous week automatically.",
        ),
    )

    THIS_MONTH = LookupDefinition(
        id="this_month",
        display_name="This Month",
        django_representation="this_month",
        aliases=["__this_month"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the current month automatically.",
        ),
    )

    LAST_MONTH = LookupDefinition(
        id="last_month",
        display_name="Last Month",
        django_representation="last_month",
        aliases=["__last_month"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the previous month automatically.",
        ),
    )

    THIS_QUARTER = LookupDefinition(
        id="this_quarter",
        display_name="This Quarter",
        django_representation="this_quarter",
        aliases=["__this_quarter"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the current quarter automatically.",
        ),
    )

    LAST_QUARTER = LookupDefinition(
        id="last_quarter",
        display_name="Last Quarter",
        django_representation="last_quarter",
        aliases=["__last_quarter"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the previous quarter automatically.",
        ),
    )

    THIS_YEAR = LookupDefinition(
        id="this_year",
        display_name="This Year",
        django_representation="this_year",
        aliases=["__this_year"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the current year automatically.",
        ),
    )

    LAST_YEAR = LookupDefinition(
        id="last_year",
        display_name="Last Year",
        django_representation="last_year",
        aliases=["__last_year"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the previous year automatically.",
        ),
    )

    YEAR = LookupDefinition(
        id="year",
        display_name="Year",
        django_representation="year",
        aliases=["__year"],
        render_func=partial(render_numeric_lookup_value, min_value=1),
    )

    MONTH = LookupDefinition(
        id="month",
        display_name="Month",
        django_representation="month",
        aliases=["__month"],
        render_func=render_month_lookup_value,
    )

    DAY = LookupDefinition(
        id="day",
        display_name="Day",
        django_representation="day",
        aliases=["__day"],
        render_func=partial(render_numeric_lookup_value, min_value=1, max_value=31),
    )

    WEEK = LookupDefinition(
        id="week",
        display_name="Week",
        django_representation="week",
        aliases=["__week"],
        render_func=partial(render_numeric_lookup_value, min_value=1, max_value=53),
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


def render_foreign_key_in(application_field:"ApplicationField", name_override: Optional[str] = None) -> str:
    from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

    field_name = name_override or application_field.field
    widget_attrs = {}
    widget_attrs.update(application_field.meta or {})
    return ForeignFieldWidget(attrs=widget_attrs).render(
        name=field_name,
        value=None,
        attrs={
            "class": "input w-full"
        }
    )
