from rest_framework import serializers
from django.db.models import Model
from rest_framework import viewsets
from bloomerp.utils.filters import dynamic_filterset_factory

def generate_serializer(model:Model):
    '''
    Dynamically generate a serializer class for a given model.
    '''

    # Dynamically create a Meta class
    meta_class = type('Meta', (object,), {
        'model': model,
        'fields': '__all__',
    })

    # Dynamically create the serializer class
    serializer_class = type(f'{model.__name__}Serializer', (serializers.ModelSerializer,), {
        'Meta': meta_class
    })

    return serializer_class


def generate_model_viewset_class(
        model:Model,
        serializer:serializers.ModelSerializer,
        base_viewset:viewsets.ModelViewSet
        ):
    '''
    Dynamically generate a viewset class for a given
    model.
    '''
    Class = type(f'{model.__name__}ViewSet', (base_viewset,), {
        'model': model,
        'serializer_class': serializer,
        'filterset_class': dynamic_filterset_factory(model)
    })



    return Class
