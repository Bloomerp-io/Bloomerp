"""
Utility functions for filtering through Django models using django-filters.
"""
from datetime import date, datetime, time, timedelta

import django_filters

from typing import Type, Optional
from django.db.models import Model
from django.db.models.query import QuerySet

from bloomerp.field_types.filter_classes import filter_class_for_model_field_path
from bloomerp.field_types.lookups import Lookup
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


def _configured_filters(
    application_field: ApplicationField,
) -> dict[str, django_filters.Filter]:
    field_type = application_field.get_field_type_enum().value
    if not field_type.allow_in_model and field_type.id != "OneToManyField":
        return {}

    configured: dict[str, django_filters.Filter] = {}
    for lookup in field_type.lookups:
        if lookup.value.filter_class_funcs:
            configured.update(
                lookup.value.filter_class_funcs(application_field)
            )
    return configured


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
    
    for field in application_fields:
        filter_overrides.update(_configured_filters(field))
            
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

        filter_cls = (
            django_filters.BooleanFilter
            if lookup_expr == "isnull"
            else filter_class_for_model_field_path(model, field_name)
        )
        filter_overrides[filter_key] = filter_cls(
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


def resolve_filter(
    model: type[Model],
    application_field: ApplicationField,
    field_path: str,
    operator: str,
) -> tuple[str, django_filters.Filter] | None:
    """Resolve a submitted field/operator pair to its configured filter."""
    if not model or not application_field or not operator:
        return None

    operator = str(operator)
    if operator.startswith("__"):
        candidates = [operator.lstrip("_")]
    else:
        field_name = (
            field_path
            if isinstance(field_path, str) and "__" in field_path
            else application_field.field
        )
        normalized_operator = operator.lstrip("_")
        candidates = [f"{field_name}__{normalized_operator}"]

        field_type = application_field.get_field_type_enum()
        lookup = field_type.get_lookup_by_id(operator)
        if lookup is None:
            lookup = next(
                (
                    candidate
                    for candidate in field_type.lookups
                    if operator == candidate.value.django_representation
                    or operator in (candidate.value.aliases or [])
                ),
                None,
            )
        if lookup is None:
            lookup = next(
                (
                    candidate
                    for candidate in Lookup
                    if operator == candidate.value.id
                    or operator == candidate.value.django_representation
                    or operator in (candidate.value.aliases or [])
                ),
                None,
            )
        if lookup is not None:
            candidates.extend(
                f"{field_name}{alias}"
                for alias in lookup.value.aliases or []
            )
            if lookup.value.django_representation:
                candidates.append(
                    f"{field_name}__{lookup.value.django_representation}"
                )

    generated_filters = _configured_filters(application_field)
    for candidate in dict.fromkeys(candidates):
        if candidate in generated_filters:
            return candidate, generated_filters[candidate]

    root_field_name = candidates[0].split("__", 1)[0]
    try:
        root_field = model._meta.get_field(root_field_name)
    except Exception:
        return None
    if not getattr(root_field, "is_relation", False):
        return None

    for candidate in dict.fromkeys(candidates):
        try:
            path_parts = candidate.split("__")
            if path_parts[-1] in DJANGO_LOOKUP_SUFFIXES:
                field_name = "__".join(path_parts[:-1])
                lookup_expr = (
                    "exact" if path_parts[-1] == "equals" else path_parts[-1]
                )
            else:
                field_name = candidate
                lookup_expr = "exact"
            filter_cls = (
                django_filters.BooleanFilter
                if lookup_expr == "isnull"
                else filter_class_for_model_field_path(model, field_name)
            )
        except Exception:
            continue
        return candidate, filter_cls(
            field_name=field_name,
            lookup_expr=lookup_expr,
            distinct=True,
        )
    return None


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
