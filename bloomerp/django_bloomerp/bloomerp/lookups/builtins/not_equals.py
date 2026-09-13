from __future__ import annotations

from typing import Any

from django.db.models import Q

from bloomerp.lookups.builtins.utils import coerce_field_value
from bloomerp.lookups.definition import (
    CompiledLookup,
    CompiledSQL,
    LookupDefinition,
    SQLLookupContext,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


def not_equals_q_factory(
    application_field: ApplicationField,
    field_path: str,
    expression: str,
    value: Any,
) -> CompiledLookup:
    del expression
    return CompiledLookup(
        predicate=~Q(**{field_path: coerce_field_value(application_field, value)})
    )


def not_equals_sql_factory(
    context: SQLLookupContext,
    expression: str,
    value: Any,
) -> CompiledSQL:
    del expression
    if value is None:
        return CompiledSQL(clause=f"{context.field_path} IS NOT NULL")
    clause = f"{context.field_path} <> %s"
    if context.nullable is not False:
        clause = f"({clause} OR {context.field_path} IS NULL)"
    return CompiledSQL(
        clause=clause,
        parameters=(value,),
    )


NOT_EQUALS = LookupDefinition(
    id="not_equals",
    label="Does not equal",
    expressions=("not_equals", "ne"),
    q_factory=not_equals_q_factory,
    sql_factory=not_equals_sql_factory,
    python_evaluator=lambda actual, expected: actual != expected,
)
