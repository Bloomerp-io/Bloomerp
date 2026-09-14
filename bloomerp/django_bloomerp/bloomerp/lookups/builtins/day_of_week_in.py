from __future__ import annotations

from bloomerp.lookups.definition import FilterFieldContext
import calendar
from typing import Any

from django import forms
from django.db.models import Q

from bloomerp.lookups.builtins.utils import as_local_date, list_value
from bloomerp.lookups.definition import (
    CompiledLookup,
    CompiledSQL,
    LookupDefinition,
    SQLLookupContext,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


def weekdays(value: Any) -> tuple[int, ...]:
    return tuple(int(item) for item in list_value(value))


def day_of_week_in_q_factory(
    application_field: ApplicationField,
    field_path: str,
    expression: str,
    value: Any,
) -> CompiledLookup:
    del application_field, expression
    return CompiledLookup(
        predicate=Q(
            **{f"{field_path}__iso_week_day__in": tuple(day + 1 for day in weekdays(value))}
        )
    )


def day_of_week_in_sql_factory(
    context: SQLLookupContext,
    expression: str,
    value: Any,
) -> CompiledSQL:
    del expression
    values = tuple(day + 1 for day in weekdays(value))
    if not values:
        return CompiledSQL(clause="1 = 0")
    return CompiledSQL(
        clause=(
            f"EXTRACT(ISODOW FROM {context.field_path}) IN "
            f"({', '.join('%s' for _ in values)})"
        ),
        parameters=values,
    )


def day_of_week_in(actual: Any, expected: Any) -> bool:
    actual_date = as_local_date(actual)
    if actual_date is None:
        return False
    try:
        return actual_date.weekday() in weekdays(expected)
    except (TypeError, ValueError):
        return False


def day_of_week_in_form_factory(
    context: FilterFieldContext,
) -> forms.MultipleChoiceField:
    del context
    return forms.MultipleChoiceField(
        required=False,
        choices=[(str(index), name) for index, name in enumerate(calendar.day_name)],
    )


DAY_OF_WEEK_IN = LookupDefinition(
    id="day_of_week_in",
    label="Day of week in",
    expressions=("day_of_week_in",),
    q_factory=day_of_week_in_q_factory,
    sql_factory=day_of_week_in_sql_factory,
    python_evaluator=day_of_week_in,
    default_form_factory=day_of_week_in_form_factory,
)
