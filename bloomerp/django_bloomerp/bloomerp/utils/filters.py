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
    ManyToManyField,
    Field
)
from bloomerp.models.fields import StatusField
from django_filters import DateFilter

from typing import Type
from django.db.models import Model
from django.db.models.query import QuerySet

def dynamic_filterset_factory(model : Type[Model]) -> Type[django_filters.FilterSet]:
    """
    Dynamically creates a FilterSet class for the given model. It generates filters
    based on field types, such as `icontains`, `exact`, and `isnull` for string fields,
    and `gte`, `lte` for date and integer fields. ForeignKey fields allow filtering on related objects.
    """
    # Create a dictionary to store dynamically created filters
    filter_overrides = {}

    # Iterate over the model's fields
    for field in model._meta.get_fields():
        field : Field

        if isinstance(field, JSONField):
            # Skip JSON fields
            continue
        
        if isinstance(field, ImageField):
            # Skip Image fields
            continue
        
        if isinstance(field, FileField):
            # Skip File fields
            continue  
        
        if isinstance(field, CharField) or isinstance(field, TextField) or isinstance(field, StatusField):
            # String fields: Add icontains, exact, and isnull filters
            filter_overrides[f'{field.name}__icontains'] = django_filters.CharFilter(field_name=field.name, lookup_expr='icontains')
            filter_overrides[f'{field.name}__isnull'] = django_filters.BooleanFilter(field_name=field.name, lookup_expr='isnull')
            filter_overrides[f'{field.name}__exact'] = django_filters.CharFilter(field_name=field.name, lookup_expr='exact')
            filter_overrides[f'{field.name}__startswith'] = django_filters.CharFilter(field_name=field.name, lookup_expr='startswith')
            filter_overrides[f'{field.name}__endswith'] = django_filters.CharFilter(field_name=field.name, lookup_expr='endswith')

        elif isinstance(field, IntegerField) or isinstance(field, BigAutoField) or isinstance(field, AutoField) or isinstance(field, DecimalField):
            # Date and Integer fields: Add gte, lte, gt, lt filters
            filter_overrides[f'{field.name}__gte'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='gte')
            filter_overrides[f'{field.name}__lte'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='lte')
            filter_overrides[f'{field.name}__gt'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='gt')
            filter_overrides[f'{field.name}__lt'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='lt')

            # Add isnull filter for IntegerField
            filter_overrides[f'{field.name}__isnull'] = django_filters.BooleanFilter(field_name=field.name, lookup_expr='isnull')
            
            # Add exact filter for IntegerField
            filter_overrides[f'{field.name}'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='exact')
            filter_overrides[f'{field.name}__equals'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='exact')
            filter_overrides[f'{field.name}__exact'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='exact')

        elif isinstance(field, DateField) or isinstance(field, DateTimeField):
            if field.get_internal_type() == 'DateField':
                # Date fields: Add gte, lte, gt, lt filters
                filter_overrides[f'{field.name}__gte'] = DateFilter(field_name=field.name, lookup_expr='gte')
                filter_overrides[f'{field.name}__lte'] = DateFilter(field_name=field.name, lookup_expr='lte')
                filter_overrides[f'{field.name}__gt'] = DateFilter(field_name=field.name, lookup_expr='gt')
                filter_overrides[f'{field.name}__lt'] = DateFilter(field_name=field.name, lookup_expr='lt')

                # Add exact filter for DateField
                filter_overrides[f'{field.name}__exact'] = DateFilter(field_name=field.name, lookup_expr='exact')
            else:
                # DateTime fields: Add gte, lte, gt, lt filters
                filter_overrides[f'{field.name}__gte'] = django_filters.DateTimeFilter(field_name=field.name, lookup_expr='gte')
                filter_overrides[f'{field.name}__lte'] = django_filters.DateTimeFilter(field_name=field.name, lookup_expr='lte')
                filter_overrides[f'{field.name}__gt'] = django_filters.DateTimeFilter(field_name=field.name, lookup_expr='gt')
                filter_overrides[f'{field.name}__lt'] = django_filters.DateTimeFilter(field_name=field.name, lookup_expr='lt')
                filter_overrides[f'{field.name}__exact'] = django_filters.DateTimeFilter(field_name=field.name, lookup_expr='exact')


            # Add isnull filter for DateField
            filter_overrides[f'{field.name}__isnull'] = django_filters.BooleanFilter(field_name=field.name, lookup_expr='isnull')

            # Add year, month, day, week filters for DateField
            filter_overrides[f'{field.name}__year'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='year')
            filter_overrides[f'{field.name}__month'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='month')
            filter_overrides[f'{field.name}__day'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='day')
            filter_overrides[f'{field.name}__week'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='week')

            # Add year, month, day gte, lte filters for DateField
            filter_overrides[f'{field.name}__year__gte'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='year__gte')
            filter_overrides[f'{field.name}__year__lte'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='year__lte')
            filter_overrides[f'{field.name}__month__gte'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='month__gte')
            filter_overrides[f'{field.name}__month__lte'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='month__lte')
            filter_overrides[f'{field.name}__day__gte'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='day__gte')
            filter_overrides[f'{field.name}__day__lte'] = django_filters.NumberFilter(field_name=field.name, lookup_expr='day__lte')

        elif isinstance(field, ForeignKey):
            # ForeignKey fields: Add filters for related model's CharField fields (e.g. manager__first_name)

            # Add isnull filter for ForeignKey
            filter_overrides[f'{field.name}__isnull'] = django_filters.BooleanFilter(field_name=field.name, lookup_expr='isnull')

            related_model = field.related_model
            related_fields = related_model._meta.get_fields()  # Assuming you want to filter by string fields in related models
            
            for related_field in related_fields:
                # For example: manager__first_name__icontains
                filter_overrides[f'{field.name}__{related_field.name}__exact'] = django_filters.CharFilter(field_name=f'{field.name}__{related_field.name}', lookup_expr='exact')
                filter_overrides[f'{field.name}__{related_field.name}'] = django_filters.CharFilter(field_name=f'{field.name}__{related_field.name}', lookup_expr='exact')
        
        elif field.get_internal_type() == 'ManyToManyField':
            # ManyToMany fields: Add filters for related model's CharField fields (e.g. functions__name__icontains)
            related_model = field.related_model
            filter_overrides[field.name] = django_filters.ModelMultipleChoiceFilter(field_name=field.name, to_field_name='id', queryset=related_model.objects.all())
            filter_overrides[f'{field.name}__id'] = django_filters.ModelMultipleChoiceFilter(field_name=field.name, to_field_name='id', queryset=related_model.objects.all())
            filter_overrides[f'{field.name}__in'] = django_filters.ModelMultipleChoiceFilter(field_name=field.name, to_field_name='id', queryset=related_model.objects.all(), lookup_expr='in', distinct=True)

            related_fields = related_model._meta.get_fields()

            for related_field in related_fields:
                filter_overrides[f'{field.name}__{related_field.name}__exact'] = django_filters.CharFilter(field_name=f'{field.name}__{related_field.name}', lookup_expr='exact')
                filter_overrides[f'{field.name}__{related_field.name}'] = django_filters.CharFilter(field_name=f'{field.name}__{related_field.name}', lookup_expr='exact')
                                

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

def filter_model(model: Type[Model], filters: dict) -> QuerySet:
    """Applies the given filters to the model's queryset using a dynamically created FilterSet."""
    FilterSet = dynamic_filterset_factory(model)
    filterset = FilterSet(filters, queryset=model.objects.all())
    