



from typing import Optional, Type

from django.db.models import Model
from django.urls import reverse

from bloomerp.models.definition import BloomerpModelConfig


def set_model_config(model:Type[Model], config:BloomerpModelConfig):
    """Set the bloomerp model config at runtime

    Args:
        model (Type[Model]): the model
        config (BloomerpModelConfig): the config
    """
    setattr(model, "bloomerp_config", config)
    
    
    
def get_model_config(model:Type[Model]) -> Optional[BloomerpModelConfig]:
    """Returns the bloomerp model config for a particular model

    Args:
        model (Type[Model]): the model

    Returns:
        Optional[BloomerpModelConfig]: the config or None
    """
    config = getattr(model, "bloomerp_config")
    
    if isinstance(config, BloomerpModelConfig):
        return config
    
    return None


def set_detail_view_url(model:Type[Model]) -> None:
    """Set's the detail view url on a model

    Args:
        model (Type[Model]): the model
        url_name (str): the url
    """
    def get_absolute_url(self):
        """
        Returns the absolute URL of the model instance.
        """
        from bloomerp.utils.models import get_detail_view_url

        return reverse(get_detail_view_url(self.__class__), kwargs={'pk': self.pk})
    
    setattr(model, "get_absolute_url", get_absolute_url) 
    
    
    