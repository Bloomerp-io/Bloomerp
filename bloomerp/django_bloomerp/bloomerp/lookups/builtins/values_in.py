from __future__ import annotations

from typing import Any

from django.db.models import Q

from bloomerp.lookups.builtins.utils import list_value, normalize_list_value
from bloomerp.lookups.definition import (
    CompiledLookup,
    CompiledSQL,
    LookupDefinition,
    SQLLookupContext,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


def values_in_q_factory(
    application_field: ApplicationField,
    field_path: str,
    expression: str,
    value: Any,
) -> CompiledLookup:
    del expression
    values = normalize_list_value(application_field, value)
    return CompiledLookup(predicate=Q(**{f"{field_path}__in": values}))


def values_in_sql_factory(
    context: SQLLookupContext,
    expression: str,
    value: Any,
) -> CompiledSQL:
    del expression
    values = list_value(value)
    if not values:
        return CompiledSQL(clause="1 = 0")
    placeholders = ", ".join("%s" for _ in values)
    return CompiledSQL(
        clause=f"{context.field_path} IN ({placeholders})",
        parameters=values,
    )


def values_in(actual: Any, expected: Any) -> bool:
    return actual in list_value(expected)


VALUES_IN = LookupDefinition(
    id="values_in",
    label="In",
    expressions=("values_in", "in"),
    description="Matches a value against a supplied list of candidates.",
    q_factory=values_in_q_factory,
    sql_factory=values_in_sql_factory,
    python_evaluator=values_in,
)
