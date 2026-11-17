from django.db.models import Model
from django.utils.module_loading import import_string
from rest_framework.serializers import ModelSerializer

from bloomerp.models.definition import get_model_config
from bloomerp.utils.api import generate_serializer

_model_serializers:dict[type[Model], type[ModelSerializer]] = {}

def set_serializer_cls(model: type[Model]) -> None:
    """Cache the configured serializer extension or the standard generated serializer."""
    config = get_model_config(model)
    path = config.api_settings.serializer_class if config and config.api_settings else None
    _model_serializers[model] = import_string(path) if path else generate_serializer(model)
    
def get_serializer_cls(model:type[Model]) -> type[ModelSerializer]:
    if model not in _model_serializers:
        set_serializer_cls(model)
    return _model_serializers[model]

