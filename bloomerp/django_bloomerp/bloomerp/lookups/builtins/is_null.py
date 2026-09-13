from __future__ import annotations

from bloomerp.lookups.definition import FilterFieldContext
from typing import Any

from django import forms
from django.db.models import Q

from bloomerp.lookups.builtins.utils import is_truthy
from bloomerp.lookups.definition import (
    CompiledLookup,
    CompiledSQL,
    LookupDefinition,
    SQLLookupContext,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


def is_null_q_factory(
    application_field: ApplicationField,
    field_path: str,
    expression: str,
    value: Any,
) -> CompiledLookup:
    del application_field, expression
    return CompiledLookup(predicate=Q(**{f"{field_path}__isnull": is_truthy(value)}))


def is_null_sql_factory(
    context: SQLLookupContext,
    expression: str,
    value: Any,
) -> CompiledSQL:
    del expression
    operator = "IS NULL" if is_truthy(value) else "IS NOT NULL"
    return CompiledSQL(clause=f"{context.field_path} {operator}")


def is_null_form_factory(context: FilterFieldContext) -> forms.BooleanField:
    del context
    return forms.BooleanField(required=False)


IS_NULL = LookupDefinition(
    id="is_null",
    label="Is null",
    expressions=("is_null", "isnull"),
    description="Matches null values when true and non-null values when false.",
    q_factory=is_null_q_factory,
    sql_factory=is_null_sql_factory,
    python_evaluator=lambda actual, expected: (actual is None) is is_truthy(expected),
    default_form_factory=is_null_form_factory,
)
