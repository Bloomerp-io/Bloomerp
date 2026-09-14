from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model
from django.utils.decorators import classonlymethod

from bloomerp.api.base import BloomerpModelViewSet
from bloomerp.models.definition import get_model_config
from bloomerp.serializers.model_serializers import get_serializer_cls


def get_auto_api_models() -> list[type[Model]]:
    api_models: list[type[Model]] = []

    for model in apps.get_models():
        if model._meta.abstract or model._meta.proxy:
            continue

        config = get_model_config(model)
        if config and not config.should_enable_api_auto_generation():
            continue
        # Only if disabled don't auto generate API
        api_models.append(model)
        
    return api_models


AUTO_API_MODELS = get_auto_api_models()


class BaseModelApiView(BloomerpModelViewSet):
    model: type[Model] | None = None
    serializer_class = None
    actions: dict[str, str] = {}

    @classonlymethod
    def as_view(cls, actions=None, **initkwargs):
        resolved_actions = actions or cls.actions
        if not resolved_actions:
            raise ImproperlyConfigured(
                f"{cls.__name__} must define a DRF action map."
            )
        return super().as_view(actions=resolved_actions, **initkwargs)

    def get_serializer_class(self):
        if self.serializer_class is not None:
            return self.serializer_class
        if self.model is None:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} requires a model."
            )
        return get_serializer_cls(self.model)
