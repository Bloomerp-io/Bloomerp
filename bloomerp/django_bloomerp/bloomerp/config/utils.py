



from typing import Optional, Type

from django.db.models import Model

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