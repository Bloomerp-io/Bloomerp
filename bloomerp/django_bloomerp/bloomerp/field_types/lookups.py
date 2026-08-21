from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime, time, timedelta

from typing import Any, Callable

import calendar
from django import forms
import django_filters

from enum import Enum

from typing import Optional
from typing import TYPE_CHECKING

from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from django.db.models import BooleanField, Count, DateField, DateTimeField, DecimalField, DurationField, Field, FloatField, IntegerField, Q, QuerySet, TextField, TimeField, UUIDField
from django.db.models.functions import Cast
from django.db.models.fields.json import KeyTextTransform
from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField
    
    
# ---------------------
# Helper functions
# ---------------------

def _is_truthy_lookup_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"

    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    value_str = str(value).strip()
    if value_str.lower() in {"true", "false"}:
        return value_str.upper()

    try:
        float(value_str)
    except (TypeError, ValueError):
        escaped_value = value_str.replace("'", "''")
        return f"'{escaped_value}'"

    return value_str


def _sql_like_value(value: Any, *, prefix: str = "", suffix: str = "") -> str:
    escaped_value = str(value).strip().replace("'", "''")
    return f"'{prefix}{escaped_value}{suffix}'"


def _sql_in_values(value: Any) -> str:
    values = value
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",")]
    elif not isinstance(value, (list, tuple, set)):
        values = [value]

    rendered_values = ", ".join(_sql_literal(item) for item in values if str(item).strip() != "")
    return f"IN ({rendered_values})"


def _sql_is_null(value: Any) -> str:
    return "IS NULL" if _is_truthy_lookup_value(value) else "IS NOT NULL"

# ---------------------
# Widget functions
# ---------------------
def _equals_widget(application_field: "ApplicationField") -> forms.Widget:
    from bloomerp.field_types.types import FieldType
    match application_field.field_type_enum:
        case FieldType.BOOLEAN_FIELD:
            return forms.Select(choices=[("true", "True"), ("false", "False")], attrs={"class": "select w-full"})
        case FieldType.FOREIGN_KEY | FieldType.ONE_TO_ONE_FIELD:
            return ForeignFieldWidget(model=application_field.related_model.model_class(), attrs={"class": "input w-full"})
        case FieldType.MANY_TO_MANY_FIELD:
            return ForeignFieldWidget(model=application_field.related_model.model_class(), attrs={"class": "input w-full", "is_m2m": True})
        case FieldType.DATE_FIELD:
            return forms.DateInput(attrs={"class": "input w-full", "type": "date"})
        case FieldType.DATE_TIME_FIELD:
            return forms.DateTimeInput(attrs={"class": "input w-full", "type": "datetime-local"})
        case _:
            return forms.TextInput(attrs={"class": "input w-full"})

def _in_widget(application_field: "ApplicationField") -> forms.Widget:
    from bloomerp.field_types.types import FieldType
    match application_field.field_type_enum:
        case FieldType.FOREIGN_KEY | FieldType.MANY_TO_MANY_FIELD:
            return ForeignFieldWidget(model=application_field.related_model.model_class(), attrs={"class": "input w-full", "is_m2m":True})
        case _:
            return forms.TextInput(attrs={"class": "input w-full", "placeholder": "Enter comma-separated values"})

def _hidden_true(application_field: "ApplicationField") -> forms.Widget:
    return forms.HiddenInput(attrs={"value": "true"})

# ---------------------
# Filter class funcs
# ---------------------
class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    pass


class AddressComponentFilterMixin:
    """Filter an address JSON component with a composable ORM condition."""

    def __init__(
        self,
        *args,
        address_field_name: str,
        component: str,
        lookup_enum: "Lookup",
        **kwargs,
    ):
        self.address_field_name = address_field_name
        self.component = component
        self.lookup_enum = lookup_enum
        super().__init__(*args, **kwargs)

    def as_q(self, value) -> Q:
        expression = Cast(
            KeyTextTransform(self.component, self.address_field_name),
            output_field=TextField(),
        )
        lookup_expr = self.lookup_enum.value.django_representation
        exclude = self.lookup_enum in {Lookup.NOT_EQUALS, Lookup.NOT_IN}
        if self.lookup_enum == Lookup.NOT_EQUALS:
            lookup_expr = "exact"
        elif self.lookup_enum == Lookup.NOT_IN:
            lookup_expr = "in"
        elif self.lookup_enum == Lookup.IS_NULL:
            lookup_expr = "isnull"

        lookup_cls = expression.get_lookup(lookup_expr)
        condition = Q(lookup_cls(expression, value))
        return ~condition if exclude else condition

    def filter(self, queryset: QuerySet, value) -> QuerySet:
        if value in django_filters.constants.EMPTY_VALUES:
            return queryset
        return queryset.filter(self.as_q(value))


class AddressCharFilter(AddressComponentFilterMixin, django_filters.CharFilter):
    pass


class AddressCharInFilter(AddressComponentFilterMixin, CharInFilter):
    pass


class AddressBooleanFilter(AddressComponentFilterMixin, django_filters.BooleanFilter):
    pass


class NumberInFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    pass


class DateInFilter(django_filters.BaseInFilter, django_filters.DateFilter):
    pass


class DateTimeInFilter(django_filters.BaseInFilter, django_filters.DateTimeFilter):
    pass


class TimeInFilter(django_filters.BaseInFilter, django_filters.TimeFilter):
    pass


class DurationInFilter(django_filters.BaseInFilter, django_filters.DurationFilter):
    pass


class UUIDInFilter(django_filters.BaseInFilter, django_filters.UUIDFilter):
    pass


class DayOfWeekInFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    def filter(self, queryset: QuerySet, value) -> QuerySet:
        if value in django_filters.constants.EMPTY_VALUES:
            return queryset

        try:
            days_of_week = [int(day) for day in value]
        except (TypeError, ValueError):
            return queryset.none()

        if any(day < 0 or day > 6 for day in days_of_week):
            return queryset.none()

        return queryset.filter(**{f"{self.field_name}__iso_week_day__in": [day + 1 for day in days_of_week]})


class CountFilter(django_filters.NumberFilter):
    def __init__(self, *args, count_lookup_expr: str = "exact", **kwargs):
        self.count_lookup_expr = count_lookup_expr
        super().__init__(*args, **kwargs)

    def filter(self, queryset: QuerySet, value) -> QuerySet:
        if value in django_filters.constants.EMPTY_VALUES:
            return queryset

        count_alias = f"_{self.field_name.replace('__', '_')}_count"
        return queryset.annotate(**{count_alias: Count(self.field_name)}).filter(
            **{f"{count_alias}__{self.count_lookup_expr}": value}
        )


def _model_field(application_field: "ApplicationField") -> Field | None:
    try:
        return application_field._get_model_field()
    except Exception:
        return None


def _filter_class_for_field(application_field: "ApplicationField") -> type[django_filters.Filter]:
    model_field = _model_field(application_field)
    if isinstance(model_field, BooleanField):
        return django_filters.BooleanFilter
    if isinstance(model_field, DateTimeField):
        return django_filters.DateTimeFilter
    if isinstance(model_field, DateField):
        return django_filters.DateFilter
    if isinstance(model_field, TimeField):
        return django_filters.TimeFilter
    if isinstance(model_field, DurationField):
        return django_filters.DurationFilter
    if isinstance(model_field, UUIDField):
        return django_filters.UUIDFilter
    if isinstance(model_field, (IntegerField, DecimalField, FloatField)):
        return django_filters.NumberFilter
    return django_filters.CharFilter


def _in_filter_class_for_field(application_field: "ApplicationField") -> type[django_filters.Filter]:
    model_field = _model_field(application_field)
    if isinstance(model_field, DateTimeField):
        return DateTimeInFilter
    if isinstance(model_field, DateField):
        return DateInFilter
    if isinstance(model_field, TimeField):
        return TimeInFilter
    if isinstance(model_field, DurationField):
        return DurationInFilter
    if isinstance(model_field, UUIDField):
        return UUIDInFilter
    if isinstance(model_field, (IntegerField, DecimalField, FloatField)):
        return NumberInFilter
    return CharInFilter


def _filter_names(application_field: "ApplicationField", lookup: "LookupDefinition") -> list[str]:
    if lookup.aliases:
        return [f"{application_field.field}{alias}" for alias in lookup.aliases]
    if lookup.django_representation:
        return [f"{application_field.field}__{lookup.django_representation}"]
    return []


def _simple_filter_classes(
    application_field: "ApplicationField",
    lookup: "LookupDefinition",
    *,
    filter_cls: type[django_filters.Filter] | None = None,
    lookup_expr: str | None = None,
) -> dict[str, django_filters.Filter]:
    filter_cls = filter_cls or _filter_class_for_field(application_field)
    lookup_expr = lookup_expr or lookup.django_representation
    return {
        name: filter_cls(field_name=application_field.field, lookup_expr=lookup_expr)
        for name in _filter_names(application_field, lookup)
    }


def _not_equals_filter_class(application_field: "ApplicationField", lookup: "LookupDefinition") -> dict[str, django_filters.Filter]:
    if _is_relation_choice_field(application_field):
        return _relation_filter_class(application_field, lookup, exclude=True)

    def filter_not_equal(queryset: QuerySet, name: str, value):
        if value in django_filters.constants.EMPTY_VALUES:
            return queryset
        return queryset.exclude(**{name: value})

    filter_cls = _filter_class_for_field(application_field)
    return {
        name: filter_cls(field_name=application_field.field, method=filter_not_equal)
        for name in _filter_names(application_field, lookup)
    }


def _address_filter_classes(application_field: "ApplicationField") -> dict[str, django_filters.Filter]:
    """Build filters for each structured address component stored in JSON."""
    from bloomerp.widgets.address_widget import ADDRESS_COMPONENTS

    filters: dict[str, django_filters.Filter] = {}
    for component, _label, _autocomplete in ADDRESS_COMPONENTS:
        field_name = f"{application_field.field}__{component}"
        for lookup_enum in get_address_component_lookups(component):
            lookup = lookup_enum.value
            names = [f"{field_name}{alias}" for alias in lookup.aliases]

            if lookup_enum == Lookup.IS_NULL:
                filter_cls = AddressBooleanFilter
            elif lookup_enum in {Lookup.IN, Lookup.NOT_IN}:
                filter_cls = AddressCharInFilter
            else:
                filter_cls = AddressCharFilter

            filters.update(
                {
                    name: filter_cls(
                        field_name=field_name,
                        address_field_name=application_field.field,
                        component=component,
                        lookup_enum=lookup_enum,
                    )
                    for name in names
                }
            )

    return filters


def _relative_date_filter_class(application_field: "ApplicationField", lookup: "LookupDefinition") -> dict[str, django_filters.Filter]:
    model_field = _model_field(application_field)
    if model_field is None:
        return {}

    return {
        name: RelativeDateRangeFilter(
            field_name=application_field.field,
            lookup_id=lookup.id,
            model_field=model_field,
        )
        for name in _filter_names(application_field, lookup)
    }


def _relation_filter_class(
    application_field: "ApplicationField",
    lookup: "LookupDefinition",
    *,
    exclude: bool = False,
) -> dict[str, django_filters.Filter]:
    related_model = application_field.get_related_model()
    if related_model is None:
        return {}

    if application_field.get_field_type_enum().value.id == "ManyToManyField":
        filter_cls = django_filters.ModelMultipleChoiceFilter
        kwargs = {
            "queryset": related_model.objects.all(),
            "to_field_name": "id",
            "distinct": True,
            "exclude": exclude,
        }
    elif lookup.id == "in":
        filter_cls = django_filters.ModelMultipleChoiceFilter
        kwargs = {
            "queryset": related_model.objects.all(),
            "widget": django_filters.widgets.CSVWidget,
            "exclude": exclude,
        }
    else:
        filter_cls = django_filters.ModelChoiceFilter
        kwargs = {"queryset": related_model.objects.all(), "exclude": exclude}

    return {
        name: filter_cls(field_name=application_field.field, **kwargs)
        for name in _filter_names(application_field, lookup)
    }


def _is_relation_choice_field(application_field: "ApplicationField") -> bool:
    return application_field.get_field_type_enum().value.id in {
        "ForeignKey",
        "OneToOneField",
        "UserField",
        "ManyToManyField",
    }


def _count_filter_class(application_field: "ApplicationField", lookup: "LookupDefinition", count_lookup_expr: str) -> dict[str, django_filters.Filter]:
    return {
        name: CountFilter(
            field_name=application_field.field,
            count_lookup_expr=count_lookup_expr,
        )
        for name in _filter_names(application_field, lookup)
    }

RELATIVE_DATE_LOOKUPS = (
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "this_quarter",
    "last_quarter",
    "this_year",
    "last_year",
)


class DayOfWeekFilter(django_filters.NumberFilter):
    def filter(self, queryset: QuerySet, value) -> QuerySet:
        if value in django_filters.constants.EMPTY_VALUES:
            return queryset

        try:
            day_of_week = int(value)
        except (TypeError, ValueError):
            return queryset.none()

        if day_of_week < 0 or day_of_week > 6:
            return queryset.none()

        # UI uses calendar.day_name order: Monday=0 ... Sunday=6.
        return queryset.filter(**{f"{self.field_name}__iso_week_day": day_of_week + 1})


def _shift_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _quarter_start(value: date) -> date:
    quarter_month = ((value.month - 1) // 3) * 3 + 1
    return date(value.year, quarter_month, 1)


def _get_relative_date_range(lookup: str, reference_date: date) -> tuple[date, date]:
    if lookup == "today":
        return reference_date, reference_date + timedelta(days=1)
    
    if lookup == "yesterday":
        start = reference_date - timedelta(days=1)
        return start, reference_date

    if lookup == "this_week":
        start = reference_date - timedelta(days=reference_date.weekday())
        return start, start + timedelta(days=7)

    if lookup == "last_week":
        end = reference_date - timedelta(days=reference_date.weekday())
        return end - timedelta(days=7), end

    if lookup == "this_month":
        start = reference_date.replace(day=1)
        return start, _shift_months(start, 1)

    if lookup == "last_month":
        end = reference_date.replace(day=1)
        start = _shift_months(end, -1)
        return start, end

    if lookup == "this_quarter":
        start = _quarter_start(reference_date)
        return start, _shift_months(start, 3)

    if lookup == "last_quarter":
        end = _quarter_start(reference_date)
        start = _shift_months(end, -3)
        return start, end

    if lookup == "this_year":
        start = date(reference_date.year, 1, 1)
        return start, date(reference_date.year + 1, 1, 1)

    if lookup == "last_year":
        start = date(reference_date.year - 1, 1, 1)
        return start, date(reference_date.year, 1, 1)

    raise ValueError(f"Unsupported relative date lookup: {lookup}")


def _coerce_relative_bounds(field: Field, start: date, end: date) -> tuple[date | datetime, date | datetime]:
    if isinstance(field, DateTimeField):
        start_dt = datetime.combine(start, time.min)
        end_dt = datetime.combine(end, time.min)
        if settings.USE_TZ:
            current_timezone = timezone.get_current_timezone()
            start_dt = timezone.make_aware(start_dt, current_timezone)
            end_dt = timezone.make_aware(end_dt, current_timezone)
        return start_dt, end_dt

    return start, end


class RelativeDateRangeFilter(django_filters.BooleanFilter):
    def __init__(self, *args, lookup_id: str, model_field: Field, **kwargs):
        self.lookup_id = lookup_id
        self.model_field = model_field
        super().__init__(*args, **kwargs)

    def filter(self, queryset: QuerySet, value: bool) -> QuerySet:
        if value in django_filters.constants.EMPTY_VALUES or value is False:
            return queryset

        start, end = _get_relative_date_range(self.lookup_id, timezone.localdate())
        range_start, range_end = _coerce_relative_bounds(self.model_field, start, end)
        return queryset.filter(
            **{
                f"{self.field_name}__gte": range_start,
                f"{self.field_name}__lt": range_end,
            }
        )


def _python_collection(value: Any) -> list | None:
    if isinstance(value, QuerySet):
        return list(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return None


def _python_equals(actual: Any, expected: Any) -> bool:
    values = _python_collection(actual)
    return expected in values if values is not None else actual == expected


def _python_compare(actual: Any, expected: Any, operator: Callable) -> bool:
    try:
        return operator(actual, expected)
    except (TypeError, ValueError):
        return False


def _python_in(actual: Any, expected: Any) -> bool:
    values = expected
    if isinstance(expected, str):
        values = [item.strip() for item in expected.split(",") if item.strip()]
    elif not isinstance(expected, (list, tuple, set, frozenset, QuerySet)):
        values = [expected]
    actual_values = _python_collection(actual)
    if actual_values is not None:
        return any(item in values for item in actual_values)
    return actual in values


def _python_as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.date()
    return value if isinstance(value, date) else None


def _python_relative_date(lookup_id: str) -> Callable[[Any, Any], bool]:
    def evaluate(actual: Any, _expected: Any) -> bool:
        actual_date = _python_as_date(actual)
        if actual_date is None:
            return False
        start, end = _get_relative_date_range(lookup_id, timezone.localdate())
        return start <= actual_date < end

    return evaluate


def _python_date_part(part: str) -> Callable[[Any, Any], bool]:
    def evaluate(actual: Any, expected: Any) -> bool:
        actual_date = _python_as_date(actual)
        if actual_date is None:
            return False
        try:
            expected_int = int(expected)
        except (TypeError, ValueError):
            return False
        if part == "week":
            return actual_date.isocalendar().week == expected_int
        if part == "day_of_week":
            return actual_date.weekday() == expected_int
        return getattr(actual_date, part) == expected_int

    return evaluate


def _python_day_of_week_in(actual: Any, expected: Any) -> bool:
    actual_date = _python_as_date(actual)
    if actual_date is None:
        return False
    values = expected
    if isinstance(values, str):
        values = [item.strip() for item in values.split(",") if item.strip()]
    try:
        return actual_date.weekday() in {int(item) for item in values}
    except (TypeError, ValueError):
        return False


def _python_count(value: Any) -> int | None:
    values = _python_collection(value)
    if values is not None:
        return len(values)
    try:
        return len(value)
    except (TypeError, AttributeError):
        return None


def _python_count_compare(operator: Callable) -> Callable[[Any, Any], bool]:
    def evaluate(actual: Any, expected: Any) -> bool:
        count = _python_count(actual)
        if count is None:
            return False
        try:
            return operator(count, int(expected))
        except (TypeError, ValueError):
            return False

    return evaluate



# ---------------------
# Defintion
# ---------------------
@dataclass
class LookupDefinition:
    id: str
    display_name: str
    django_representation: str  # The Django ORM lookup (e.g., "icontains", "gte")
    description: Optional[str] = None

    # Filter configuration for django-filters
    aliases: list[str] = dataclass_field(default_factory=list)  # Alternative field name patterns: ["", "__exact", "__equals"]

    # SQL
    sql_operator: Callable[[Any], str] = lambda value: f"= {_sql_literal(value)}"
    
    def render(self, application_field, name_override: Optional[str] = None) -> str:
        return self.widget_func(application_field).render(
            name=name_override or application_field.field,
            value=None,
        )

    # Widget function
    widget_func: Optional[Callable[["ApplicationField"], forms.Widget]] = lambda application_field: forms.TextInput(attrs={"class": "input w-full"})
    
    # Filter class function
    filter_class_funcs : Optional[Callable[["ApplicationField"], dict[str, django_filters.Filter]]] = None
    
    # Python operator
    python_eval : Optional[Callable[[Any, Any], bool]] = None


class Lookup(Enum):
    EQUALS = LookupDefinition(
        id="equals",
        display_name="Equals",
        django_representation="exact",
        aliases=["", "__exact", "__equals"],  # Can use field_name, field_name__exact, or field_name__equals
        sql_operator=lambda value: f"= {_sql_literal(value)}",
        widget_func=_equals_widget,
        filter_class_funcs=lambda value, lookup=None: (
            _relation_filter_class(value, lookup or Lookup.EQUALS.value)
            if _is_relation_choice_field(value)
            else _simple_filter_classes(value, lookup or Lookup.EQUALS.value)
        ),
        python_eval=_python_equals,
    )
    
    IEXACT = LookupDefinition(
        id="iexact",
        display_name="Equals (case-insensitive)",
        django_representation="iexact",
        aliases=["__iexact"],
        description="Case-insensitive exact match.",
        sql_operator=lambda value: f"LIKE {_sql_literal(value)}",
        widget_func=_equals_widget,
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.IEXACT.value, filter_cls=django_filters.CharFilter),
        python_eval=lambda actual, expected: str(actual).casefold() == str(expected).casefold(),
    )

    CONTAINS = LookupDefinition(
        id="contains",
        display_name="Contains",
        django_representation="icontains",
        aliases=["__icontains", "__contains"],
        description="Containment test (generated as icontains by default).",
        sql_operator=lambda value: f"LIKE {_sql_like_value(value, prefix='%', suffix='%')}",
        widget_func=_equals_widget,
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.CONTAINS.value, filter_cls=django_filters.CharFilter),
        python_eval=lambda actual, expected: str(expected).casefold() in str(actual).casefold(),
    )

    STARTS_WITH = LookupDefinition(
        id="starts_with",
        display_name="Starts With",
        django_representation="startswith",
        aliases=["__startswith", "__istartswith"],
        description="Starts with test.",
        sql_operator=lambda value: f"LIKE {_sql_like_value(value, suffix='%')}",
        widget_func=_equals_widget,
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.STARTS_WITH.value, filter_cls=django_filters.CharFilter),
        python_eval=lambda actual, expected: str(actual).startswith(str(expected)),
    )

    ENDS_WITH = LookupDefinition(
        id="ends_with",
        display_name="Ends With",
        django_representation="endswith",
        aliases=["__endswith", "__iendswith"],
        description="Ends with test.",
        sql_operator=lambda value: f"LIKE {_sql_like_value(value, prefix='%')}",
        widget_func=_equals_widget,
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.ENDS_WITH.value, filter_cls=django_filters.CharFilter),
        python_eval=lambda actual, expected: str(actual).endswith(str(expected)),
    )

    GREATER_THAN = LookupDefinition(
        id="greater_than",
        display_name="Greater Than",
        django_representation="gt",
        aliases=["__gt"],
        sql_operator=lambda value: f"> {_sql_literal(value)}",
        widget_func=_equals_widget,
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.GREATER_THAN.value),
        python_eval=lambda actual, expected: _python_compare(actual, expected, lambda a, b: a > b),
    )

    GREATER_THAN_OR_EQUAL = LookupDefinition(
        id="greater_than_or_equal",
        display_name="Greater Than or Equal",
        django_representation="gte",
        aliases=["__gte"],
        sql_operator=lambda value: f">= {_sql_literal(value)}",
        widget_func=_equals_widget,
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.GREATER_THAN_OR_EQUAL.value),
        python_eval=lambda actual, expected: _python_compare(actual, expected, lambda a, b: a >= b),
    )

    LESS_THAN = LookupDefinition(
        id="less_than",
        display_name="Less Than",
        django_representation="lt",
        aliases=["__lt"],
        sql_operator=lambda value: f"< {_sql_literal(value)}",
        widget_func=_equals_widget,
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.LESS_THAN.value),
        python_eval=lambda actual, expected: _python_compare(actual, expected, lambda a, b: a < b),
    )

    LESS_THAN_OR_EQUAL = LookupDefinition(
        id="less_than_or_equal",
        display_name="Less Than or Equal",
        django_representation="lte",
        aliases=["__lte"],
        sql_operator=lambda value: f"<= {_sql_literal(value)}",
        widget_func=_equals_widget,
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.LESS_THAN_OR_EQUAL.value),
        python_eval=lambda actual, expected: _python_compare(actual, expected, lambda a, b: a <= b),
    )

    IN = LookupDefinition(
        id="in",
        display_name="In",
        django_representation="in",
        aliases=["__in"],
        description="Checks if value is in a list of values.",
        sql_operator=_sql_in_values,
        widget_func=_in_widget,
        filter_class_funcs=lambda value, lookup=None: (
            _relation_filter_class(value, lookup or Lookup.IN.value)
            if _is_relation_choice_field(value)
            else _simple_filter_classes(value, lookup or Lookup.IN.value, filter_cls=_in_filter_class_for_field(value))
        ),
        python_eval=_python_in,
    )

    IS_NULL = LookupDefinition(
        id="is_null",
        display_name="Is Null",
        django_representation="isnull",
        aliases=["__isnull"],
        description="Checks if value is null (True) or not null (False).",
        sql_operator=_sql_is_null,
        widget_func=lambda _: forms.Select(choices=[("true", "True"), ("false", "False")], attrs={"class": "select w-full"}),
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.IS_NULL.value, filter_cls=django_filters.BooleanFilter),
        python_eval=lambda actual, expected: (actual is None) is bool(expected),
    )

    NOT_EQUALS = LookupDefinition(
        id="not_equals",
        display_name="Not Equals",
        django_representation="ne",
        aliases=["__ne", "__not_equals"],
        description="Not equal comparison.",
        sql_operator=lambda value: f"!= {_sql_literal(value)}",
        widget_func=_equals_widget,
        filter_class_funcs=lambda value, lookup=None: _not_equals_filter_class(value, lookup or Lookup.NOT_EQUALS.value),
        python_eval=lambda actual, expected: not _python_equals(actual, expected),
    )

    NOT_IN = LookupDefinition(
        id="not_in",
        display_name="Not In",
        django_representation="not_in",
        aliases=["__not_in"],
        description="Checks if value is not in a list of values.",
        sql_operator=lambda value: f"NOT {_sql_in_values(value)}",
        widget_func=_in_widget,
        python_eval=lambda actual, expected: not _python_in(actual, expected),
    )

    ADDRESS_ADVANCED = LookupDefinition(
        id="address_advanced",
        display_name="Address Lookup",
        django_representation="",
        filter_class_funcs=_address_filter_classes,
    )

    EQUALS_USER = LookupDefinition(
        id="equals_user",
        display_name="Equals Current User",
        django_representation="",
        widget_func=lambda x: forms.HiddenInput(attrs={"value": "$user"}),
        python_eval=_python_equals,
    )

    FOREIGN_ADVANCED = LookupDefinition(
        id="foreign_advanced",
        display_name="Advanced Lookup",
        django_representation="",
    )

    ONE_TO_MANY_ADVANCED = LookupDefinition(
        id="one_to_many_advanced",
        display_name="Advanced Lookup",
        django_representation="",
    )

    TODAY = LookupDefinition(
        id="today",
        display_name="Today",
        django_representation="today",
        aliases=["__today"],
        widget_func=_hidden_true,
        filter_class_funcs=lambda value, lookup=None: _relative_date_filter_class(value, lookup or Lookup.TODAY.value),
        python_eval=_python_relative_date("today"),
    )

    YESTERDAY = LookupDefinition(
        id="yesterday",
        display_name="Yesterday",
        django_representation="yesterday",
        aliases=["__yesterday"],
        widget_func=_hidden_true,
        filter_class_funcs=lambda value, lookup=None: _relative_date_filter_class(value, lookup or Lookup.YESTERDAY.value),
        python_eval=_python_relative_date("yesterday"),
    )

    THIS_WEEK = LookupDefinition(
        id="this_week",
        display_name="This Week",
        django_representation="this_week",
        aliases=["__this_week"],
        widget_func=_hidden_true,
        filter_class_funcs=lambda value, lookup=None: _relative_date_filter_class(value, lookup or Lookup.THIS_WEEK.value),
        python_eval=_python_relative_date("this_week"),
    )

    LAST_WEEK = LookupDefinition(
        id="last_week",
        display_name="Last Week",
        django_representation="last_week",
        aliases=["__last_week"],
        widget_func=_hidden_true,
        filter_class_funcs=lambda value, lookup=None: _relative_date_filter_class(value, lookup or Lookup.LAST_WEEK.value),
        python_eval=_python_relative_date("last_week"),
    )

    THIS_MONTH = LookupDefinition(
        id="this_month",
        display_name="This Month",
        django_representation="this_month",
        aliases=["__this_month"],
        widget_func=_hidden_true,
        filter_class_funcs=lambda value, lookup=None: _relative_date_filter_class(value, lookup or Lookup.THIS_MONTH.value),
        python_eval=_python_relative_date("this_month"),
    )

    LAST_MONTH = LookupDefinition(
        id="last_month",
        display_name="Last Month",
        django_representation="last_month",
        aliases=["__last_month"],
        widget_func=_hidden_true,
        filter_class_funcs=lambda value, lookup=None: _relative_date_filter_class(value, lookup or Lookup.LAST_MONTH.value),
        python_eval=_python_relative_date("last_month"),
    )

    THIS_QUARTER = LookupDefinition(
        id="this_quarter",
        display_name="This Quarter",
        django_representation="this_quarter",
        aliases=["__this_quarter"],
        widget_func=_hidden_true,
        filter_class_funcs=lambda value, lookup=None: _relative_date_filter_class(value, lookup or Lookup.THIS_QUARTER.value),
        python_eval=_python_relative_date("this_quarter"),
    )

    LAST_QUARTER = LookupDefinition(
        id="last_quarter",
        display_name="Last Quarter",
        django_representation="last_quarter",
        aliases=["__last_quarter"],
        widget_func=_hidden_true,
        filter_class_funcs=lambda value, lookup=None: _relative_date_filter_class(value, lookup or Lookup.LAST_QUARTER.value),
        python_eval=_python_relative_date("last_quarter"),
    )

    THIS_YEAR = LookupDefinition(
        id="this_year",
        display_name="This Year",
        django_representation="this_year",
        aliases=["__this_year"],
        widget_func=_hidden_true,
        filter_class_funcs=lambda value, lookup=None: _relative_date_filter_class(value, lookup or Lookup.THIS_YEAR.value),
        python_eval=_python_relative_date("this_year"),
    )

    LAST_YEAR = LookupDefinition(
        id="last_year",
        display_name="Last Year",
        django_representation="last_year",
        aliases=["__last_year"],
        widget_func=_hidden_true,
        filter_class_funcs=lambda value, lookup=None: _relative_date_filter_class(value, lookup or Lookup.LAST_YEAR.value),
        python_eval=_python_relative_date("last_year"),
    )

    YEAR = LookupDefinition(
        id="year",
        display_name="Year",
        django_representation="year",
        aliases=["__year"],
        widget_func=lambda x: forms.NumberInput(attrs={"class": "input w-full", "min": 1, "max": 9999, "type": "number"}),
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.YEAR.value, filter_cls=django_filters.NumberFilter),
        python_eval=_python_date_part("year"),
    )

    MONTH = LookupDefinition(
        id="month",
        display_name="Month",
        django_representation="month",
        aliases=["__month"],
        widget_func=lambda x: forms.NumberInput(attrs={"class": "input w-full", "min": 1, "max": 12, "type": "number"}),
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.MONTH.value, filter_cls=django_filters.NumberFilter),
        python_eval=_python_date_part("month"),
    )

    DAY = LookupDefinition(
        id="day",
        display_name="Day",
        django_representation="day",
        aliases=["__day"],
        widget_func=lambda x: forms.NumberInput(attrs={"class": "input w-full", "min": 1, "max": 31, "type": "number"}),
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.DAY.value, filter_cls=django_filters.NumberFilter),
        python_eval=_python_date_part("day"),
    )

    WEEK = LookupDefinition(
        id="week",
        display_name="Week",
        django_representation="week",
        aliases=["__week"],
        widget_func=lambda application_field: forms.NumberInput(attrs={"class": "input w-full", "min": 1, "max": 53, "type": "number"}),
        filter_class_funcs=lambda value, lookup=None: _simple_filter_classes(value, lookup or Lookup.WEEK.value, filter_cls=django_filters.NumberFilter),
        python_eval=_python_date_part("week"),
    )
    
    DAY_OF_WEEK = LookupDefinition(
        id="day_of_week",
        display_name="Day of Week",
        django_representation="day_of_week",
        aliases=["__day_of_week"],
        widget_func=lambda application_field: forms.Select(choices=[(str(i), calendar.day_name[i]) for i in range(7)], attrs={"class": "select w-full"}),
        filter_class_funcs=lambda value, lookup=None: {
            name: DayOfWeekFilter(field_name=value.field)
            for name in _filter_names(value, lookup or Lookup.DAY_OF_WEEK.value)
        },
        python_eval=_python_date_part("day_of_week"),
    )
    
    DAY_OF_WEEK_IN = LookupDefinition(
        id="day_of_week_in",
        display_name="Day of Week In",
        django_representation="day_of_week_in",
        aliases=["__day_of_week_in"],
        widget_func=lambda application_field: forms.SelectMultiple(choices=[(str(i), calendar.day_name[i]) for i in range(7)], attrs={"class": "select w-full"}),
        filter_class_funcs=lambda value, lookup=None: {
            name: DayOfWeekInFilter(field_name=value.field)
            for name in _filter_names(value, lookup or Lookup.DAY_OF_WEEK_IN.value)
        },
        python_eval=_python_day_of_week_in,
    )

    COUNT_EQUALS = LookupDefinition(
        id="count_equals",
        display_name="Count Equals",
        django_representation="count",
        aliases=["__count", "__count__exact", "__count_equals"],
        widget_func=lambda application_field: forms.NumberInput(attrs={"class": "input w-full", "min": 0, "type": "number"}),
        filter_class_funcs=lambda value, lookup=None: _count_filter_class(value, lookup or Lookup.COUNT_EQUALS.value, "exact"),
        python_eval=_python_count_compare(lambda a, b: a == b),
    )

    COUNT_GREATER_THAN = LookupDefinition(
        id="count_greater_than",
        display_name="Count Greater Than",
        django_representation="count__gt",
        aliases=["__count__gt", "__count_greater_than"],
        widget_func=lambda application_field: forms.NumberInput(attrs={"class": "input w-full", "min": 0, "type": "number"}),
        filter_class_funcs=lambda value, lookup=None: _count_filter_class(value, lookup or Lookup.COUNT_GREATER_THAN.value, "gt"),
        python_eval=_python_count_compare(lambda a, b: a > b),
    )

    COUNT_GREATER_THAN_OR_EQUAL = LookupDefinition(
        id="count_greater_than_or_equal",
        display_name="Count Greater Than or Equal",
        django_representation="count__gte",
        aliases=["__count__gte", "__count_greater_than_or_equal"],
        widget_func=lambda application_field: forms.NumberInput(attrs={"class": "input w-full", "min": 0, "type": "number"}),
        filter_class_funcs=lambda value, lookup=None: _count_filter_class(value, lookup or Lookup.COUNT_GREATER_THAN_OR_EQUAL.value, "gte"),
        python_eval=_python_count_compare(lambda a, b: a >= b),
    )

    COUNT_LESS_THAN = LookupDefinition(
        id="count_less_than",
        display_name="Count Less Than",
        django_representation="count__lt",
        aliases=["__count__lt", "__count_less_than"],
        widget_func=lambda application_field: forms.NumberInput(attrs={"class": "input w-full", "min": 0, "type": "number"}),
        filter_class_funcs=lambda value, lookup=None: _count_filter_class(value, lookup or Lookup.COUNT_LESS_THAN.value, "lt"),
        python_eval=_python_count_compare(lambda a, b: a < b),
    )

    COUNT_LESS_THAN_OR_EQUAL = LookupDefinition(
        id="count_less_than_or_equal",
        display_name="Count Less Than or Equal",
        django_representation="count__lte",
        aliases=["__count__lte", "__count_less_than_or_equal"],
        widget_func=lambda application_field: forms.NumberInput(attrs={"class": "input w-full", "min": 0, "type": "number"}),
        filter_class_funcs=lambda value, lookup=None: _count_filter_class(value, lookup or Lookup.COUNT_LESS_THAN_OR_EQUAL.value, "lte"),
        python_eval=_python_count_compare(lambda a, b: a <= b),
    )
    
    

DATE_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.GREATER_THAN,
    Lookup.GREATER_THAN_OR_EQUAL,
    Lookup.LESS_THAN,
    Lookup.LESS_THAN_OR_EQUAL,
    Lookup.TODAY,
    Lookup.YESTERDAY,
    Lookup.THIS_WEEK,
    Lookup.LAST_WEEK,
    Lookup.THIS_MONTH,
    Lookup.LAST_MONTH,
    Lookup.THIS_QUARTER,
    Lookup.LAST_QUARTER,
    Lookup.THIS_YEAR,
    Lookup.LAST_YEAR,
    Lookup.YEAR,
    Lookup.MONTH,
    Lookup.DAY,
    Lookup.WEEK,
    Lookup.IS_NULL,
    Lookup.NOT_EQUALS,
    Lookup.DAY_OF_WEEK,
    Lookup.DAY_OF_WEEK_IN,
]

WEEK_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.GREATER_THAN,
    Lookup.GREATER_THAN_OR_EQUAL,
    Lookup.LESS_THAN,
    Lookup.LESS_THAN_OR_EQUAL,
    Lookup.YEAR,
    Lookup.WEEK,
    Lookup.IS_NULL,
    Lookup.NOT_EQUALS,
]

TIME_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.GREATER_THAN,
    Lookup.GREATER_THAN_OR_EQUAL,
    Lookup.LESS_THAN,
    Lookup.LESS_THAN_OR_EQUAL,
    Lookup.IS_NULL,
    Lookup.NOT_EQUALS,
]

ONE_TO_MANY_LOOKUPS = [
    Lookup.ONE_TO_MANY_ADVANCED,
    Lookup.COUNT_EQUALS,
    Lookup.COUNT_GREATER_THAN,
    Lookup.COUNT_GREATER_THAN_OR_EQUAL,
    Lookup.COUNT_LESS_THAN,
    Lookup.COUNT_LESS_THAN_OR_EQUAL,
]

BOOLEAN_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.IS_NULL,
]

NUMERIC_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.GREATER_THAN,
    Lookup.GREATER_THAN_OR_EQUAL,
    Lookup.LESS_THAN,
    Lookup.LESS_THAN_OR_EQUAL,
    Lookup.IN,
    Lookup.IS_NULL,
    Lookup.NOT_EQUALS,
]

TEXT_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.IEXACT,
    Lookup.CONTAINS,
    Lookup.STARTS_WITH,
    Lookup.ENDS_WITH,
    Lookup.IN,
    Lookup.IS_NULL,
    Lookup.NOT_EQUALS,
]

ADDRESS_COUNTRY_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.NOT_EQUALS,
    Lookup.IS_NULL,
    Lookup.IN,
    Lookup.NOT_IN,
]


def get_address_component_lookups(component: str) -> list[Lookup]:
    """Return the supported lookups for a structured address component."""
    return ADDRESS_COUNTRY_LOOKUPS if component == "country" else TEXT_LOOKUPS
