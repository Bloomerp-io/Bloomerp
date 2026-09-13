from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone

from bloomerp.lookups.builtins.utils import (
    as_local_date,
    no_value_form_factory,
    normalize_date_bounds,
    normalize_sql_date_bounds,
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


def today_q_factory(
    application_field: ApplicationField,
    field_path: str,
    expression: str,
    value: Any,
) -> CompiledLookup:
    del expression, value
    start = timezone.localdate()
    start, end = normalize_date_bounds(
        application_field,
        start,
        start + timedelta(days=1),
    )
    return CompiledLookup(
        predicate=Q(**{f"{field_path}__gte": start, f"{field_path}__lt": end})
    )


def today_sql_factory(
    context: SQLLookupContext,
    expression: str,
    value: Any,
) -> CompiledSQL:
    del expression, value
    start = timezone.localdate()
    start, end = normalize_sql_date_bounds(
        context,
        start,
        start + timedelta(days=1),
    )
    return CompiledSQL(
        clause=f"{context.field_path} >= %s AND {context.field_path} < %s",
        parameters=(start, end),
    )


def is_today(actual: Any, expected: Any) -> bool:
    del expected
    return as_local_date(actual) == timezone.localdate()


TODAY = LookupDefinition(
    id="today",
    label="Today",
    expressions=("today",),
    description="Matches dates that fall on the current local day.",
    q_factory=today_q_factory,
    sql_factory=today_sql_factory,
    python_evaluator=is_today,
    default_form_factory=no_value_form_factory,
)
