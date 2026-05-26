from rest_framework.serializers import ModelSerializer
from django.db.models import Model
from bloomerp.utils.api import generate_serializer

_model_serializers:dict[type[Model], type[ModelSerializer]] = {}

def set_serializer_cls(model:type[Model]):
    _model_serializers[model] = generate_serializer(model)
    
def get_serializer_cls(model:type[Model]) -> type[ModelSerializer]:
    if model not in _model_serializers:
        set_serializer_cls(model)
    return _model_serializers[model]

