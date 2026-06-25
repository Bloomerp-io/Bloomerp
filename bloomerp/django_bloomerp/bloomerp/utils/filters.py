"""
Utility functions for filtering through Django models using django-filters.
"""
from datetime import date, datetime, time, timedelta

import django_filters
from django.conf import settings
from django.db.models import (
    ForeignKey, 
    BooleanField,
    CharField, 
    DateField, 
    IntegerField,
    TextField,
    JSONField,
    ImageField,
    FileField,
    DateTimeField,
    BigAutoField,
    AutoField,
    DecimalField,
    FloatField,
    UUIDField,
    Field
)
from bloomerp.model_fields.status_field import StatusField
from bloomerp.model_fields.week_field import WeekField
from django_filters import DateFilter
from django.utils import timezone

from typing import Type, Optional
from django.db.models import Model
from django.db.models.query import QuerySet

MAX_RELATION_FILTER_DEPTH = 6

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

def dynamic_filterset_factory(model : Type[Model]) -> Type[django_filters.FilterSet]:
    """
    Dynamically creates a FilterSet class for the given model. It generates filters
    based on field types, such as `icontains`, `exact`, and `isnull` for string fields,
    and `gte`, `lte` for date and integer fields. ForeignKey fields allow filtering on related objects.
    """
    # Create a dictionary to store dynamically created filters
    filter_overrides = {}

    def filter_not_equal(queryset: QuerySet, name: str, value):
        if value in django_filters.constants.EMPTY_VALUES:
            return queryset
        return queryset.exclude(**{name: value})

    def add_scalar_filters(field: Field, prefix: str) -> None:
        field_name = f"{prefix}{field.name}"

        if isinstance(field, JSONField):
            return
        if isinstance(field, ImageField):
            return
        if isinstance(field, FileField):
            return

        if isinstance(field, WeekField):
            filter_overrides[f'{field_name}'] = django_filters.CharFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__exact'] = django_filters.CharFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__gte'] = django_filters.CharFilter(field_name=field_name, lookup_expr='gte')
            filter_overrides[f'{field_name}__lte'] = django_filters.CharFilter(field_name=field_name, lookup_expr='lte')
            filter_overrides[f'{field_name}__gt'] = django_filters.CharFilter(field_name=field_name, lookup_expr='gt')
            filter_overrides[f'{field_name}__lt'] = django_filters.CharFilter(field_name=field_name, lookup_expr='lt')
            filter_overrides[f'{field_name}__year'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='year')
            filter_overrides[f'{field_name}__week'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='week')
            filter_overrides[f'{field_name}__isnull'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='isnull')
            filter_overrides[f'{field_name}__ne'] = django_filters.CharFilter(field_name=field_name, method=filter_not_equal)
            return

        if isinstance(field, BooleanField):
            filter_overrides[f'{field_name}'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__equals'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__exact'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__isnull'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='isnull')
            return

        if isinstance(field, CharField) or isinstance(field, TextField) or isinstance(field, StatusField):
            filter_overrides[f'{field_name}'] = django_filters.CharFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__icontains'] = django_filters.CharFilter(field_name=field_name, lookup_expr='icontains')
            filter_overrides[f'{field_name}__isnull'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='isnull')
            filter_overrides[f'{field_name}__exact'] = django_filters.CharFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__startswith'] = django_filters.CharFilter(field_name=field_name, lookup_expr='startswith')
            filter_overrides[f'{field_name}__endswith'] = django_filters.CharFilter(field_name=field_name, lookup_expr='endswith')
            return

        if isinstance(field, IntegerField) or isinstance(field, BigAutoField) or isinstance(field, AutoField) or isinstance(field, DecimalField) or isinstance(field, FloatField):
            filter_overrides[f'{field_name}__gte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='gte')
            filter_overrides[f'{field_name}__lte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='lte')
            filter_overrides[f'{field_name}__gt'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='gt')
            filter_overrides[f'{field_name}__lt'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='lt')
            filter_overrides[f'{field_name}__isnull'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='isnull')
            filter_overrides[f'{field_name}'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__equals'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__exact'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='exact')
            return

        if isinstance(field, UUIDField):
            filter_overrides[f'{field_name}'] = django_filters.UUIDFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__equals'] = django_filters.UUIDFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__exact'] = django_filters.UUIDFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__isnull'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='isnull')
            return

        if isinstance(field, DateField) or isinstance(field, DateTimeField):
            if field.get_internal_type() == 'DateField':
                filter_overrides[f'{field_name}__gte'] = DateFilter(field_name=field_name, lookup_expr='gte')
                filter_overrides[f'{field_name}__lte'] = DateFilter(field_name=field_name, lookup_expr='lte')
                filter_overrides[f'{field_name}__gt'] = DateFilter(field_name=field_name, lookup_expr='gt')
                filter_overrides[f'{field_name}__lt'] = DateFilter(field_name=field_name, lookup_expr='lt')
                filter_overrides[f'{field_name}__exact'] = DateFilter(field_name=field_name, lookup_expr='exact')
            else:
                filter_overrides[f'{field_name}__gte'] = django_filters.DateTimeFilter(field_name=field_name, lookup_expr='gte')
                filter_overrides[f'{field_name}__lte'] = django_filters.DateTimeFilter(field_name=field_name, lookup_expr='lte')
                filter_overrides[f'{field_name}__gt'] = django_filters.DateTimeFilter(field_name=field_name, lookup_expr='gt')
                filter_overrides[f'{field_name}__lt'] = django_filters.DateTimeFilter(field_name=field_name, lookup_expr='lt')
                filter_overrides[f'{field_name}__exact'] = django_filters.DateTimeFilter(field_name=field_name, lookup_expr='exact')

            for relative_lookup in RELATIVE_DATE_LOOKUPS:
                filter_overrides[f"{field_name}__{relative_lookup}"] = RelativeDateRangeFilter(
                    field_name=field_name,
                    lookup_id=relative_lookup,
                    model_field=field,
                )

            filter_overrides[f'{field_name}__isnull'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='isnull')
            filter_overrides[f'{field_name}__year'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='year')
            filter_overrides[f'{field_name}__month'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='month')
            filter_overrides[f'{field_name}__day'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='day')
            filter_overrides[f'{field_name}__week'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='week')
            filter_overrides[f'{field_name}__day_of_week'] = DayOfWeekFilter(field_name=field_name)
            filter_overrides[f'{field_name}__year__gte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='year__gte')
            filter_overrides[f'{field_name}__year__lte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='year__lte')
            filter_overrides[f'{field_name}__month__gte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='month__gte')
            filter_overrides[f'{field_name}__month__lte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='month__lte')
            filter_overrides[f'{field_name}__day__gte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='day__gte')
            filter_overrides[f'{field_name}__day__lte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='day__lte')
            return

    def add_model_filters(current_model: Type[Model], prefix: str = "", depth: int = 0) -> None:
        for field in current_model._meta.get_fields():
            field = field  # type: Field

            if not getattr(field, "concrete", False):
                continue

            if isinstance(field, ForeignKey):
                field_name = f"{prefix}{field.name}"
                related_model = field.related_model
                if related_model:
                    filter_overrides[field_name] = django_filters.ModelChoiceFilter(
                        field_name=field_name,
                        queryset=related_model.objects.all(),
                    )
                    filter_overrides[f'{field_name}__exact'] = django_filters.ModelChoiceFilter(
                        field_name=field_name,
                        queryset=related_model.objects.all(),
                    )
                    filter_overrides[f'{field_name}__id'] = django_filters.NumberFilter(
                        field_name=f"{field_name}__id",
                        lookup_expr='exact',
                    )
                    filter_overrides[f'{field_name}__id__exact'] = django_filters.NumberFilter(
                        field_name=f"{field_name}__id",
                        lookup_expr='exact',
                    )
                filter_overrides[f'{field_name}__isnull'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='isnull')
                if depth < MAX_RELATION_FILTER_DEPTH:
                    if related_model:
                        add_model_filters(related_model, prefix=f"{field_name}__", depth=depth + 1)
                continue

            if field.many_to_many and not field.auto_created:
                field_name = f"{prefix}{field.name}"
                related_model = field.related_model
                if related_model:
                    filter_overrides[field_name] = django_filters.ModelMultipleChoiceFilter(
                        field_name=field_name,
                        to_field_name='id',
                        queryset=related_model.objects.all(),
                        distinct=True,
                    )
                    filter_overrides[f'{field_name}__exact'] = django_filters.ModelMultipleChoiceFilter(
                        field_name=field_name,
                        to_field_name='id',
                        queryset=related_model.objects.all(),
                        distinct=True,
                    )
                    filter_overrides[f'{field_name}__id'] = django_filters.ModelMultipleChoiceFilter(
                        field_name=field_name,
                        to_field_name='id',
                        queryset=related_model.objects.all(),
                        distinct=True,
                    )
                    filter_overrides[f'{field_name}__in'] = django_filters.ModelMultipleChoiceFilter(
                        field_name=field_name,
                        to_field_name='id',
                        queryset=related_model.objects.all(),
                        lookup_expr='in',
                        distinct=True
                    )
                if depth < MAX_RELATION_FILTER_DEPTH and related_model:
                    add_model_filters(related_model, prefix=f"{field_name}__", depth=depth + 1)
                continue

            add_scalar_filters(field, prefix)

    add_model_filters(model)

    # Meta class for FilterSet
    meta_class = type('Meta', (object,), {
        'model': model,
        'fields': '__all__',  # We are dynamically adding fields to the filterset
        'filter_overrides': {
            JSONField: {'filter_class': django_filters.CharFilter, 'extra': lambda f: {'lookup_expr': 'exact'}},
            ImageField: {'filter_class': django_filters.CharFilter, 'extra': lambda f: {'lookup_expr': 'exact'}},
            FileField: {'filter_class': django_filters.CharFilter, 'extra': lambda f: {'lookup_expr': 'exact'}},
        }
    })

    # Create the FilterSet class
    filterset_class = type(f'{model.__name__}FilterSet', (django_filters.FilterSet,), {
        'Meta': meta_class,
        **filter_overrides  # Dynamically generated filters are added here
    })

    return filterset_class

def filter_model(model: Type[Model], filters: dict, queryset:Optional[QuerySet]=None) -> QuerySet:
    """Filters a model based on the given queryparameters

    Args:
        model (Type[Model]): the model class
        filters (dict): the filters
        queryset (Optional[QuerySet], optional): The starting queryset. Defaults to None.

    Returns:
        QuerySet: the filtered queryset
    """
    FilterSet = dynamic_filterset_factory(model)
    qs = queryset if queryset is not None else model.objects.all()
    
    filterset = FilterSet(
        data=filters,
        queryset=qs
    )
    return filterset.qs
