from .utils.reader import load_all_models_from_modules

# Automatically load all models from YAML configurations
try:
    _dynamic_models = load_all_models_from_modules()
    
    # Add each model to the module's globals so Django can find them
    for model_name, model_class in _dynamic_models.items():
        globals()[model_class.__name__] = model_class
        
except Exception as e:
    # If loading fails, log the error but don't break Django startup
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"Failed to load dynamic models: {e}")
    _dynamic_models = {}

# Export the loaded models for easy access
__all__ = list(_dynamic_models.keys()) if _dynamic_models else []


