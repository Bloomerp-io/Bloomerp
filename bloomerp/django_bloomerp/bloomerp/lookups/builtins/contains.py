from __future__ import annotations

from bloomerp.lookups.definition import FilterFieldContext
from typing import Any

from django import forms

from bloomerp.lookups.builtins.utils import q_factory_for
from bloomerp.lookups.definition import CompiledSQL, LookupDefinition, SQLLookupContext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


def contains(actual: Any, expected: Any) -> bool:
    if actual is None or expected is None:
        return False
    return str(expected).casefold() in str(actual).casefold()


def contains_form_factory(context: FilterFieldContext) -> forms.CharField:
    del context
    return forms.CharField(required=False)


def contains_sql_factory(
    context: SQLLookupContext,
    expression: str,
    value: Any,
) -> CompiledSQL:
    del expression
    pattern = f"%{value}%"
    if context.dialect == "postgres":
        return CompiledSQL(
            clause=f"{context.field_path} ILIKE %s",
            parameters=(pattern,),
        )
    return CompiledSQL(
        clause=f"LOWER({context.field_path}) LIKE LOWER(%s)",
        parameters=(pattern,),
    )


CONTAINS = LookupDefinition(
    id="contains",
    label="Contains",
    expressions=("contains", "icontains"),
    description="Matches text containing the supplied value, ignoring case.",
    q_factory=q_factory_for("icontains"),
    sql_factory=contains_sql_factory,
    python_evaluator=contains,
    default_form_factory=contains_form_factory,
)
