from __future__ import annotations

from bloomerp.lookups.definition import FilterFieldContext
from typing import Any

from django import forms

from bloomerp.lookups.builtins.utils import q_factory_for, sql_factory_for
from bloomerp.lookups.definition import LookupDefinition
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


def ends_with(actual: Any, expected: Any) -> bool:
    if actual is None or expected is None:
        return False
    return str(actual).endswith(str(expected))


def ends_with_form_factory(
    context: FilterFieldContext,
) -> forms.CharField:
    del context
    return forms.CharField(required=False)


ENDS_WITH = LookupDefinition(
    id="ends_with",
    label="Ends with",
    expressions=("ends_with", "endswith"),
    description="Matches values ending with the supplied text.",
    q_factory=q_factory_for("endswith"),
    sql_factory=sql_factory_for("LIKE", lambda value: f"%{value}"),
    python_evaluator=ends_with,
    default_form_factory=ends_with_form_factory,
)
