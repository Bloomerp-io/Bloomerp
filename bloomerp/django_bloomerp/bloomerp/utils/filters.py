"""
Utility functions for filtering through Django models using django-filters.
"""
import django_filters
from django.db.models import (
    ForeignKey, 
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
    Field
)
from bloomerp.model_fields.status_field import StatusField
from django_filters import DateFilter

from typing import Type, Optional
from django.db.models import Model
from django.db.models.query import QuerySet

MAX_RELATION_FILTER_DEPTH = 2

def dynamic_filterset_factory(model : Type[Model]) -> Type[django_filters.FilterSet]:
    """
    Dynamically creates a FilterSet class for the given model. It generates filters
    based on field types, such as `icontains`, `exact`, and `isnull` for string fields,
    and `gte`, `lte` for date and integer fields. ForeignKey fields allow filtering on related objects.
    """
    # Create a dictionary to store dynamically created filters
    filter_overrides = {}

    def add_scalar_filters(field: Field, prefix: str) -> None:
        field_name = f"{prefix}{field.name}"

        if isinstance(field, JSONField):
            return
        if isinstance(field, ImageField):
            return
        if isinstance(field, FileField):
            return

        if isinstance(field, CharField) or isinstance(field, TextField) or isinstance(field, StatusField):
            filter_overrides[f'{field_name}__icontains'] = django_filters.CharFilter(field_name=field_name, lookup_expr='icontains')
            filter_overrides[f'{field_name}__isnull'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='isnull')
            filter_overrides[f'{field_name}__exact'] = django_filters.CharFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__startswith'] = django_filters.CharFilter(field_name=field_name, lookup_expr='startswith')
            filter_overrides[f'{field_name}__endswith'] = django_filters.CharFilter(field_name=field_name, lookup_expr='endswith')
            return

        if isinstance(field, IntegerField) or isinstance(field, BigAutoField) or isinstance(field, AutoField) or isinstance(field, DecimalField):
            filter_overrides[f'{field_name}__gte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='gte')
            filter_overrides[f'{field_name}__lte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='lte')
            filter_overrides[f'{field_name}__gt'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='gt')
            filter_overrides[f'{field_name}__lt'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='lt')
            filter_overrides[f'{field_name}__isnull'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='isnull')
            filter_overrides[f'{field_name}'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__equals'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='exact')
            filter_overrides[f'{field_name}__exact'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='exact')
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

            filter_overrides[f'{field_name}__isnull'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='isnull')
            filter_overrides[f'{field_name}__year'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='year')
            filter_overrides[f'{field_name}__month'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='month')
            filter_overrides[f'{field_name}__day'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='day')
            filter_overrides[f'{field_name}__week'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='week')
            filter_overrides[f'{field_name}__year__gte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='year__gte')
            filter_overrides[f'{field_name}__year__lte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='year__lte')
            filter_overrides[f'{field_name}__month__gte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='month__gte')
            filter_overrides[f'{field_name}__month__lte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='month__lte')
            filter_overrides[f'{field_name}__day__gte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='day__gte')
            filter_overrides[f'{field_name}__day__lte'] = django_filters.NumberFilter(field_name=field_name, lookup_expr='day__lte')
            return

    def add_model_filters(current_model: Type[Model], prefix: str = "", depth: int = 0, seen: Optional[set[str]] = None) -> None:
        if seen is None:
            seen = set()

        model_label = current_model._meta.label_lower
        if model_label in seen:
            return
        seen.add(model_label)

        for field in current_model._meta.get_fields():
            field = field  # type: Field

            if not getattr(field, "concrete", False):
                continue

            if isinstance(field, ForeignKey):
                field_name = f"{prefix}{field.name}"
                filter_overrides[f'{field_name}__isnull'] = django_filters.BooleanFilter(field_name=field_name, lookup_expr='isnull')
                if depth < MAX_RELATION_FILTER_DEPTH:
                    related_model = field.related_model
                    if related_model:
                        add_model_filters(related_model, prefix=f"{field_name}__", depth=depth + 1, seen=set(seen))
                continue

            if field.many_to_many and not field.auto_created:
                field_name = f"{prefix}{field.name}"
                related_model = field.related_model
                if related_model:
                    filter_overrides[field_name] = django_filters.ModelMultipleChoiceFilter(
                        field_name=field_name,
                        to_field_name='id',
                        queryset=related_model.objects.all()
                    )
                    filter_overrides[f'{field_name}__id'] = django_filters.ModelMultipleChoiceFilter(
                        field_name=field_name,
                        to_field_name='id',
                        queryset=related_model.objects.all()
                    )
                    filter_overrides[f'{field_name}__in'] = django_filters.ModelMultipleChoiceFilter(
                        field_name=field_name,
                        to_field_name='id',
                        queryset=related_model.objects.all(),
                        lookup_expr='in',
                        distinct=True
                    )
                if depth < MAX_RELATION_FILTER_DEPTH and related_model:
                    add_model_filters(related_model, prefix=f"{field_name}__", depth=depth + 1, seen=set(seen))
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
