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

from bloomerp.models.application_field import ApplicationField


DJANGO_LOOKUP_SUFFIXES = {
    "exact",
    "equals",
    "iexact",
    "icontains",
    "contains",
    "startswith",
    "istartswith",
    "endswith",
    "iendswith",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "isnull",
    "year",
    "month",
    "day",
    "week",
}


def dynamic_filterset_factory(model: type[Model], filters:dict[str, str]=None) -> type[django_filters.FilterSet]:
    """
    Dynamically creates a FilterSet class for the given model and filters.
    This function is similar to `dynamic_filterset_factory` but allows for additional filters to be passed in.
    """
    filter_overrides = {}
    
    application_fields = ApplicationField.get_for_model(model)
    if filters:
        included_fields = [field.split("__")[0] for field in filters.keys()]    
        application_fields = application_fields.filter(
            field__in=included_fields
        )
    
    initiated_fields = set()
    
    for field in application_fields:
        field_type = field.get_field_type_enum().value
        if not field_type.allow_in_model and field_type.id != "OneToManyField":
            continue
        
        for lookup in field_type.lookups:
            if not lookup.value.filter_class_funcs:
                continue
            
            filter_overrides.update(lookup.value.filter_class_funcs(field))
            initiated_fields.add(field.field)
            
    for filter_key in filters or {}:
        if filter_key in filter_overrides or "__" not in filter_key:
            continue

        path_parts = filter_key.split("__")
        if path_parts[-1] in DJANGO_LOOKUP_SUFFIXES:
            field_name = "__".join(path_parts[:-1])
            lookup_expr = "exact" if path_parts[-1] == "equals" else path_parts[-1]
        else:
            field_name = filter_key
            lookup_expr = "exact"

        filter_overrides[filter_key] = django_filters.CharFilter(
            field_name=field_name,
            lookup_expr=lookup_expr,
            distinct=True,
        )

    MetaCls = type(
        'Meta',
        (object,),
        {
            "model" : model,
            "fields" : []
        }
    )
    filterset_class = type(f'{model.__name__}FilterSet', (django_filters.FilterSet,), {
        'Meta': MetaCls,
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
    FilterSet = dynamic_filterset_factory(model, filters)
    qs = queryset if queryset is not None else model.objects.all()
    
    filterset = FilterSet(
        data=filters,
        queryset=qs
    )
    return filterset.qs
