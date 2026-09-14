from typing import Any

from bloomerp.lookups.builtins.utils import q_factory_for, sql_factory_for
from bloomerp.lookups.definition import FilterFieldContext, LookupDefinition
from django import forms

def equals(actual: Any, expected: Any) -> bool:
    return actual == expected


def equals_form_factory(context: FilterFieldContext) -> forms.Field:
    return context.get_form_field()


EQUALS = LookupDefinition(
    id="equals",
    label="Equals",
    expressions=("", "exact", "equals", "eq"),
    q_factory=q_factory_for(""),
    sql_factory=sql_factory_for("="),
    python_evaluator=equals,
    default_form_factory=equals_form_factory,
)
