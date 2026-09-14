from __future__ import annotations

from datetime import date
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


def month_bounds() -> tuple[date, date]:
    today = timezone.localdate()
    start = today.replace(day=1)
    end = (
        date(start.year + 1, 1, 1)
        if start.month == 12
        else date(start.year, start.month + 1, 1)
    )
    return start, end


def this_month_q_factory(
    application_field: ApplicationField,
    field_path: str,
    expression: str,
    value: Any,
) -> CompiledLookup:
    del expression, value
    start, end = normalize_date_bounds(application_field, *month_bounds())
    return CompiledLookup(
        predicate=Q(**{f"{field_path}__gte": start, f"{field_path}__lt": end})
    )


def this_month_sql_factory(
    context: SQLLookupContext,
    expression: str,
    value: Any,
) -> CompiledSQL:
    del expression, value
    start, end = normalize_sql_date_bounds(context, *month_bounds())
    return CompiledSQL(
        clause=f"{context.field_path} >= %s AND {context.field_path} < %s",
        parameters=(start, end),
    )


def is_this_month(actual: Any, expected: Any) -> bool:
    del expected
    actual_date = as_local_date(actual)
    if actual_date is None:
        return False
    start, end = month_bounds()
    return start <= actual_date < end


THIS_MONTH = LookupDefinition(
    id="this_month",
    label="This month",
    expressions=("this_month",),
    description="Matches dates that fall in the current local month.",
    q_factory=this_month_q_factory,
    sql_factory=this_month_sql_factory,
    python_evaluator=is_this_month,
    default_form_factory=no_value_form_factory,
)
