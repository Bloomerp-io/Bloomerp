from __future__ import annotations

from bloomerp.lookups.definition import FilterFieldContext
import calendar
from typing import Any

from django import forms
from django.db.models import Q

from bloomerp.lookups.builtins.utils import as_local_date
from bloomerp.lookups.definition import (
    CompiledLookup,
    CompiledSQL,
    LookupDefinition,
    SQLLookupContext,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


def day_of_week_q_factory(
    application_field: ApplicationField,
    field_path: str,
    expression: str,
    value: Any,
) -> CompiledLookup:
    del application_field, expression
    return CompiledLookup(predicate=Q(**{f"{field_path}__iso_week_day": int(value) + 1}))


def day_of_week_sql_factory(
    context: SQLLookupContext,
    expression: str,
    value: Any,
) -> CompiledSQL:
    del expression
    return CompiledSQL(
        clause=f"EXTRACT(ISODOW FROM {context.field_path}) = %s",
        parameters=(int(value) + 1,),
    )


def day_of_week(actual: Any, expected: Any) -> bool:
    actual_date = as_local_date(actual)
    try:
        return actual_date is not None and actual_date.weekday() == int(expected)
    except (TypeError, ValueError):
        return False


def day_of_week_form_factory(context: FilterFieldContext) -> forms.ChoiceField:
    del context
    return forms.ChoiceField(
        required=False,
        choices=[(str(index), name) for index, name in enumerate(calendar.day_name)],
    )


DAY_OF_WEEK = LookupDefinition(
    id="day_of_week",
    label="Day of week",
    expressions=("day_of_week",),
    q_factory=day_of_week_q_factory,
    sql_factory=day_of_week_sql_factory,
    python_evaluator=day_of_week,
    default_form_factory=day_of_week_form_factory,
)
