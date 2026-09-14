from __future__ import annotations

from bloomerp.lookups.definition import FilterFieldContext

from collections.abc import Callable, Iterable
from datetime import date, datetime, time, timedelta
from typing import Any

from django import forms
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db.models import Count, DateTimeField, Q
from django.utils import timezone

from bloomerp.lookups.definition import (
    CompiledLookup,
    CompiledSQL,
    LookupFormFactory,
    QFactory,
    SQLFactory,
    SQLLookupContext,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


def coerce_field_value(application_field: ApplicationField, value: Any) -> Any:
    """Use the concrete Django field to normalize a serialized lookup value."""

    try:
        model_field = application_field._get_model_field()
    except FieldDoesNotExist:
        return value

    try:
        return model_field.to_python(value)
    except (TypeError, ValueError, ValidationError):
        return value


def is_nullable(application_field: ApplicationField) -> bool:
    """Return whether the concrete Django field permits database nulls."""

    try:
        return application_field._get_model_field().null
    except FieldDoesNotExist:
        return False


def q_factory_for(django_expression: str) -> QFactory:
    """Build a Q factory for a fixed Django lookup expression."""

    def q_factory(
        application_field: ApplicationField,
        field_path: str,
        expression: str,
        value: Any,
    ) -> CompiledLookup:
        del expression
        resolved_path = "__".join(
            part for part in (field_path, django_expression) if part
        )
        return CompiledLookup(
            predicate=Q(
                **{
                    resolved_path: coerce_field_value(application_field, value),
                }
            )
        )

    return q_factory


def normalize_list_value(
    application_field: ApplicationField,
    value: Any,
) -> tuple[Any, ...]:
    """Normalize CSV or iterable input using the concrete Django field."""

    values = list_value(value)
    return tuple(coerce_field_value(application_field, item) for item in values)


def list_value(value: Any) -> tuple[Any, ...]:
    """Normalize CSV, iterable, and scalar values to one immutable sequence."""

    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
        return tuple(value)
    return (value,)


def sql_factory_for(
    operator: str,
    value_transform: Callable[[Any], Any] | None = None,
) -> SQLFactory:
    """Build a parameterized SQL comparison factory."""

    def sql_factory(
        context: SQLLookupContext,
        expression: str,
        value: Any,
    ) -> CompiledSQL:
        del expression
        if operator == "=" and value is None:
            return CompiledSQL(clause=f"{context.field_path} IS NULL")
        if value_transform is not None:
            value = value_transform(value)
        return CompiledSQL(
            clause=f"{context.field_path} {operator} %s",
            parameters=(value,),
        )

    return sql_factory


def compare(actual: Any, expected: Any, operator: Callable[[Any, Any], bool]) -> bool:
    """Evaluate an ordered comparison without leaking type errors."""

    if actual is not None and not isinstance(expected, type(actual)):
        try:
            expected = type(actual)(expected)
        except (TypeError, ValueError):
            return False

    try:
        return operator(actual, expected)
    except (TypeError, ValueError):
        return False


def no_value_form_factory(context: FilterFieldContext) -> forms.Field:
    """Return the hidden field used by lookups that need no user-entered value."""

    del context
    return forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.HiddenInput(attrs={"value": "true"}),
    )


def normalize_date_bounds(
    application_field: ApplicationField,
    start: date,
    end: date,
) -> tuple[date | datetime, date | datetime]:
    """Use datetime boundaries when the application field stores datetimes."""

    try:
        model_field = application_field._get_model_field()
    except FieldDoesNotExist:
        return start, end

    if not isinstance(model_field, DateTimeField):
        return start, end

    start_datetime = datetime.combine(start, time.min)
    end_datetime = datetime.combine(end, time.min)
    if settings.USE_TZ:
        current_timezone = timezone.get_current_timezone()
        start_datetime = timezone.make_aware(start_datetime, current_timezone)
        end_datetime = timezone.make_aware(end_datetime, current_timezone)
    return start_datetime, end_datetime


def normalize_sql_date_bounds(
    context: SQLLookupContext,
    start: date,
    end: date,
) -> tuple[date | datetime, date | datetime]:
    """Use datetime boundaries when SQL metadata identifies a timestamp."""

    sql_type = (context.sql_type or "").lower()
    if "timestamp" not in sql_type and "datetime" not in sql_type:
        return start, end

    start_datetime = datetime.combine(start, time.min)
    end_datetime = datetime.combine(end, time.min)
    if settings.USE_TZ:
        current_timezone = timezone.get_current_timezone()
        start_datetime = timezone.make_aware(start_datetime, current_timezone)
        end_datetime = timezone.make_aware(end_datetime, current_timezone)
    return start_datetime, end_datetime


def as_local_date(value: Any) -> date | None:
    """Normalize date and datetime values for relative-date evaluation."""

    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.date()
    return value if isinstance(value, date) else None


def is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def shift_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    return date(
        value.year + month_index // 12,
        month_index % 12 + 1,
        1,
    )


def quarter_start(value: date) -> date:
    return date(value.year, ((value.month - 1) // 3) * 3 + 1, 1)


def relative_date_bounds(period: str, reference: date) -> tuple[date, date]:
    if period == "today":
        return reference, reference + timedelta(days=1)
    if period == "yesterday":
        return reference - timedelta(days=1), reference
    if period == "this_week":
        start = reference - timedelta(days=reference.weekday())
        return start, start + timedelta(days=7)
    if period == "last_week":
        end = reference - timedelta(days=reference.weekday())
        return end - timedelta(days=7), end
    if period == "this_month":
        start = reference.replace(day=1)
        return start, shift_months(start, 1)
    if period == "last_month":
        end = reference.replace(day=1)
        return shift_months(end, -1), end
    if period == "this_quarter":
        start = quarter_start(reference)
        return start, shift_months(start, 3)
    if period == "last_quarter":
        end = quarter_start(reference)
        return shift_months(end, -3), end
    if period == "this_year":
        return date(reference.year, 1, 1), date(reference.year + 1, 1, 1)
    if period == "last_year":
        return date(reference.year - 1, 1, 1), date(reference.year, 1, 1)
    raise ValueError(f"Unsupported relative date period: {period}")


def relative_date_lookup(
    *,
    lookup_id: str,
    label: str,
):
    """Build one of the no-value, local-calendar range lookups."""
    from bloomerp.lookups.definition import LookupDefinition

    def q_factory(application_field, field_path, expression, value):
        del expression, value
        start, end = relative_date_bounds(lookup_id, timezone.localdate())
        start, end = normalize_date_bounds(application_field, start, end)
        return CompiledLookup(
            predicate=Q(**{f"{field_path}__gte": start, f"{field_path}__lt": end})
        )

    def sql_factory(context, expression, value):
        del expression, value
        start, end = relative_date_bounds(lookup_id, timezone.localdate())
        start, end = normalize_sql_date_bounds(context, start, end)
        return CompiledSQL(
            clause=(
                f"{context.field_path} >= %s AND "
                f"{context.field_path} < %s"
            ),
            parameters=(start, end),
        )

    def evaluator(actual, expected):
        del expected
        actual_date = as_local_date(actual)
        if actual_date is None:
            return False
        start, end = relative_date_bounds(lookup_id, timezone.localdate())
        return start <= actual_date < end

    return LookupDefinition(
        id=lookup_id,
        label=label,
        expressions=(lookup_id,),
        q_factory=q_factory,
        sql_factory=sql_factory,
        python_evaluator=evaluator,
        default_form_factory=no_value_form_factory,
    )


def integer_form_factory(
    *,
    min_value: int,
    max_value: int | None = None,
) -> LookupFormFactory:
    def factory(context: FilterFieldContext) -> forms.IntegerField:
        del context
        return forms.IntegerField(
            required=False,
            min_value=min_value,
            max_value=max_value,
        )

    return factory


def date_part_lookup(
    *,
    lookup_id: str,
    label: str,
    django_expression: str,
    min_value: int,
    max_value: int,
):
    """Build a numeric calendar-component lookup."""
    from bloomerp.lookups.definition import LookupDefinition

    def q_factory(application_field, field_path, expression, value):
        del application_field, expression
        return CompiledLookup(
            predicate=Q(**{f"{field_path}__{django_expression}": int(value)})
        )

    def evaluator(actual: Any, expected: Any) -> bool:
        actual_date = as_local_date(actual)
        if actual_date is None:
            return False
        try:
            expected_number = int(expected)
        except (TypeError, ValueError):
            return False
        if lookup_id == "week":
            return actual_date.isocalendar().week == expected_number
        return getattr(actual_date, lookup_id) == expected_number

    def sql_factory(context, expression, value):
        del expression
        return CompiledSQL(
            clause=(
                f"EXTRACT({django_expression.upper()} FROM "
                f"{context.field_path}) = %s"
            ),
            parameters=(int(value),),
        )

    return LookupDefinition(
        id=lookup_id,
        label=label,
        expressions=(lookup_id,),
        q_factory=q_factory,
        sql_factory=sql_factory,
        python_evaluator=evaluator,
        default_form_factory=integer_form_factory(
            min_value=min_value,
            max_value=max_value,
        ),
    )


def collection_count(value: Any) -> int | None:
    if isinstance(value, (list, tuple, set, frozenset)):
        return len(value)
    try:
        return len(value)
    except (TypeError, AttributeError):
        return None


def count_lookup(
    *,
    lookup_id: str,
    label: str,
    django_expression: str,
    sql_operator: str,
    comparator: Callable[[int, int], bool],
    expressions: tuple[str, ...] | None = None,
):
    """Build a relationship-count lookup backed by an ORM annotation."""
    from bloomerp.lookups.definition import LookupDefinition

    def q_factory(application_field, field_path, expression, value):
        del application_field, expression
        alias = f"_{field_path.replace('__', '_')}_count"
        predicate_path = "__".join(
            part for part in (alias, django_expression) if part
        )
        return CompiledLookup(
            predicate=Q(**{predicate_path: int(value)}),
            annotations={alias: Count(field_path)},
        )

    def sql_factory(context, expression, value):
        del expression
        return CompiledSQL(
            clause=f"COUNT({context.field_path}) {sql_operator} %s",
            parameters=(int(value),),
        )

    def evaluator(actual, expected):
        count = collection_count(actual)
        if count is None:
            return False
        try:
            return comparator(count, int(expected))
        except (TypeError, ValueError):
            return False

    return LookupDefinition(
        id=lookup_id,
        label=label,
        expressions=expressions or (lookup_id, f"count__{django_expression}"),
        q_factory=q_factory,
        sql_factory=sql_factory,
        python_evaluator=evaluator,
        default_form_factory=integer_form_factory(min_value=0),
    )
