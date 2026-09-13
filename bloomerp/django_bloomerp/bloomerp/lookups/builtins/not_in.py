from __future__ import annotations

from typing import Any

from django.db.models import Q

from bloomerp.lookups.builtins.utils import (
    list_value,
    normalize_list_value,
)
from bloomerp.lookups.definition import (
    CompiledLookup,
    CompiledSQL,
    LookupDefinition,
    SQLLookupContext,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


def not_in_q_factory(
    application_field: ApplicationField,
    field_path: str,
    expression: str,
    value: Any,
) -> CompiledLookup:
    del expression
    values = normalize_list_value(application_field, value)
    return CompiledLookup(predicate=~Q(**{f"{field_path}__in": values}))


def not_in_sql_factory(
    context: SQLLookupContext,
    expression: str,
    value: Any,
) -> CompiledSQL:
    del expression
    values = list_value(value)
    if not values:
        return CompiledSQL(clause="1 = 1")
    placeholders = ", ".join("%s" for _ in values)
    clause = f"{context.field_path} NOT IN ({placeholders})"
    if context.nullable is not False:
        clause = f"({clause} OR {context.field_path} IS NULL)"
    return CompiledSQL(
        clause=clause,
        parameters=values,
    )


def not_in(actual: Any, expected: Any) -> bool:
    return actual not in list_value(expected)


NOT_IN = LookupDefinition(
    id="not_in",
    label="Not in",
    expressions=("not_in", "nin"),
    q_factory=not_in_q_factory,
    sql_factory=not_in_sql_factory,
    python_evaluator=not_in,
)
