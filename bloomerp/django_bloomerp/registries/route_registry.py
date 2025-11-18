from dataclasses import dataclass
from django.db.models import Model
from functools import wraps
from typing import List, Callable, Union
from enum import Enum
import os
import importlib
import glob
import re
import logging
from typing import Optional
from datetime import datetime
from django.views import View

logger = logging.getLogger(__name__)

# ------------------------
# Data classes
# ------------------------
class RouteType(Enum):
    APP = "app"
    LIST = "list"
    DETAIL = "detail"

class ViewType(Enum):
    CLASS = "class"
    FUNCTION = "function"

@dataclass
class BloomerpRoute:
    path: str
    route_type: str
    name: str
    url_name: str
    view_type: ViewType
    view: Callable | View
    model: Optional[Model] = None
    description: str = None
    override: bool = False
    args : Optional[dict] = None


def _auto_generate_url_name(name:Optional[str], route_type:RouteType, model:Optional[Model] = None) -> str:
    """Auto generates a url name based on the given parameters"""
    def _transform_str(value:str) -> str:
        if value is None:
            return "unnamed_route"
        return value.lower().replace(" ","_")
    
    if route_type in [RouteType.DETAIL, RouteType.LIST] and model is None:
        raise ValueError(f"Model required for '{route_type.value}' route type")
        
    match route_type:
        case RouteType.APP:
            return _transform_str(name)
        case RouteType.DETAIL:
            return _transform_str(model._meta.verbose_name_plural) + "_" + route_type.value + "_" + _transform_str(name)
        case RouteType.LIST:
            return _transform_str(model._meta.verbose_name_plural) + "_" + _transform_str(name)
        case _:
            raise ValueError("Invalid route type")

def _generate_path(path: str, route_type: RouteType, model: Optional[Model] = None) -> str:
    """Generate the full path for a route"""
    # Validate that models are provided for routes that need them
    if route_type in [RouteType.DETAIL, RouteType.LIST] and not model:
        raise ValueError(f"Model required for route type '{route_type.value}'")
    
    # Ensure path has proper slashes
    if path and not path.startswith('/'):
        path = '/' + path
    if path and not path.endswith('/'):
        path = path + '/'
    
    # Handle different route types
    if route_type == RouteType.APP:
        return path if path else "/app-route/"
    
    elif route_type == RouteType.LIST:
        # Get model plural name and convert to URL-friendly format
        model_plural = model._meta.verbose_name_plural.lower().replace(' ', '-')
        if path:
            return f"/{model_plural}{path}"
        else:
            return f"/{model_plural}/"
    
    elif route_type == RouteType.DETAIL:
        # Get model singular name and convert to URL-friendly format
        model_name = model._meta.verbose_name.lower().replace(' ', '-')
        if path:
            return f"/{model_name}/<int_or_uuid:pk>{path}"
        else:
            return f"/{model_name}/<int_or_uuid:pk>/"
    
    else:
        return path if path else "/auto-route/"

def _retrieve_models(models, exclude_models, route_type: RouteType) -> list[Model]:
    """Retrieves the used models from the parameters"""
    if route_type == RouteType.APP:
        return [None]  # App routes don't need models
    
    if not models and not exclude_models:
        return [None]
    
    if models and not exclude_models:
        if models == "__all__":
            from django.apps import apps
            return apps.get_models()
        if isinstance(models, list):
            return models
        if isinstance(models, Model.__class__):
            return [models]
    
    if models and exclude_models:
        raise ValueError("Does not accept both 'models' and 'exclude_models' parameters") 
    
    if exclude_models:
        from django.apps import apps
        all_models = apps.get_models()
        if isinstance(exclude_models, list):
            return [model for model in all_models if model not in exclude_models]
        else:
            return [model for model in all_models if model != exclude_models]
    
    return [None]
    
def _generate_name(name: Optional[str]=None, model: Optional[Model]=None, view: Optional[Callable|View]=None) -> str:
    """Auto-generate a descriptive name including model information"""
    if not name and not model and not view:
        raise Exception("At least one argument needs to be given")
    
    # If name is provided, handle it
    if name:
        # Check if name has {model} placeholder that needs formatting
        if model and "{model}" in name:
            try:
                return name.format(model=model._meta.verbose_name.lower())
            except Exception:
                return name
        else:
            # Return name as-is if no formatting needed
            return name
    
    # If no name but we have model and view, generate from view name
    if not name and model and view:
        if hasattr(view, '__name__'):
            # Function-based view - convert snake_case to readable format
            view_name = view.__name__.replace('_', ' ').lower()
            return view_name
        elif hasattr(view, '__class__'):
            # Class-based view - convert CamelCase to readable format
            class_name = view.__class__.__name__
            # Add spaces before capital letters and convert to lowercase
            import re
            readable_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', class_name).lower()
            return readable_name
    
    # If we only have view (no name, no model), still try to generate from view
    if view and not name:
        if hasattr(view, '__name__'):
            return view.__name__.replace('_', ' ').lower()
        elif hasattr(view, '__class__'):
            class_name = view.__class__.__name__
            import re
            readable_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', class_name).lower()
            return readable_name
    
    # If we have model but no view and no name, we can't generate anything meaningful
    if model and not view and not name:
        raise Exception("Unable to generate name with provided arguments")
    
    # If nothing matches, raise error
    raise Exception("Unable to generate name with provided arguments")

def _generate_description(name: Optional[str]=None, model: Optional[Model]=None, view: Optional[Callable|View]=None) -> str:
    """Auto-generate a descriptive name including model information"""
    if not name and not model and not view:
        raise Exception("At least one argument needs to be given")
    
    # If name is provided, handle it
    if name:
        # Check if name has {model} placeholder that needs formatting
        if model and "{model}" in name:
            try:
                return name.format(model=model._meta.verbose_name.lower())
            except Exception:
                return name
        else:
            # Return name as-is if no formatting needed
            return name
    
    # If no name but we have model and view, generate from view name
    if not name and model and view:
        if hasattr(view, '__name__'):
            # Function-based view - convert snake_case to readable format
            view_name = view.__name__.replace('_', ' ').lower()
            return view_name
        elif hasattr(view, '__class__'):
            # Class-based view - convert CamelCase to readable format
            class_name = view.__class__.__name__
            # Add spaces before capital letters and convert to lowercase
            import re
            readable_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', class_name).lower()
            return readable_name
    
    # If we only have view (no name, no model), still try to generate from view
    if view and not name:
        if hasattr(view, '__name__'):
            return view.__name__.replace('_', ' ').lower()
        elif hasattr(view, '__class__'):
            class_name = view.__class__.__name__
            import re
            readable_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', class_name).lower()
            return readable_name
    
    # If we have model but no view and no name, we can't generate anything meaningful
    if model and not view and not name:
        raise Exception("Unable to generate name with provided arguments")
    
    # If nothing matches, raise error
    raise Exception("Unable to generate name with provided arguments")



# ------------------------
# Route registry
# ------------------------
class BloomerpRouteRegistry:
    """
    A route registry for registering both function-based and class-based views
    with Django models using decorators.
    """
    
    def __init__(self, dirs:list[str]=None):
        self.routes: List[BloomerpRoute] = []
        self._auto_imported = False
        self.dirs = dirs or []

    def _auto_import_views(self):
        """
        Automatically import all Python files in the directories specified in self.dirs
        to ensure route registrations are executed.
        """
        if self._auto_imported:
            return
            
        try:
            # Get all installed Django apps
            from django.apps import apps
            for app_config in apps.get_app_configs():
                app_path = app_config.path
                
                # Iterate through all configured directories
                for dir_name in self.dirs:
                    dir_path = os.path.join(app_path, dir_name)
                    
                    # Check if directory exists
                    if os.path.exists(dir_path) and os.path.isdir(dir_path):
                        # Find all Python files recursively in the directory
                        for root, dirs, files in os.walk(dir_path):
                            for file in files:
                                if not file.endswith('.py') or file == '__init__.py':
                                    continue
                                
                                file_path = os.path.join(root, file)
                                
                                # Convert file path to module name
                                relative_path = os.path.relpath(file_path, app_path)
                                module_path = relative_path.replace(os.path.sep, '.').replace('.py', '')
                                module_name = f"{app_config.name}.{module_path}"
                                
                                try:
                                    importlib.import_module(module_name)
                                    logger.debug(f"Successfully imported: {module_name}")
                                except (ImportError, AttributeError, ModuleNotFoundError) as e:
                                    # Log but don't fail - some files might not be valid modules
                                    logger.debug(f"Could not import {module_name}: {e}")
                                except Exception as e:
                                    # Log unexpected errors but continue
                                    logger.warning(f"Unexpected error importing {module_name}: {e}")
                    
                    # Also check for direct file (e.g., views.py, components.py)
                    direct_file = os.path.join(app_path, f'{dir_name}.py')
                    if os.path.exists(direct_file):
                        try:
                            module_name = f"{app_config.name}.{dir_name}"
                            importlib.import_module(module_name)
                            logger.debug(f"Successfully imported: {module_name}")
                        except (ImportError, AttributeError, ModuleNotFoundError) as e:
                            logger.debug(f"Could not import {module_name}: {e}")
                        except Exception as e:
                            logger.warning(f"Unexpected error importing {module_name}: {e}")
                        
            self._auto_imported = True
            logger.info(f"Auto-import completed. Registered {len(self.routes)} routes.")
            
            
        except Exception as e:
            # If anything goes wrong, log it but continue - better to have some routes than none
            logger.error(f"Error during auto-import: {e}", exc_info=True)
            self._auto_imported = True
    
    def register(
        self, 
        path: str = None,
        route_type: str = 'app',
        models: Union[Model, List[Model], str, None] = None,
        exclude_models:Union[Model, List[Model], str, None] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        url_name: Optional[str] = None,
        override: bool = False,
    ):
        """
        Decorator for registering routes with the registry.
        Works for both function-based and class-based views.
        
        Args:
            path: The URL path for the route (optional, auto-generated if not provided)
            models: The model(s) associated with this route
            route_type: Type of route ('app', 'list', 'detail')
            name: Name for the route (optional, derived from view if not provided)
            description: Description of the route
            override: Whether to override existing routes with same path
        """
        def decorator(view):
            # Use local variables to avoid nonlocal complications
            _name = name
            _description = description
            _path = path
            _url_name = url_name
            
            # Determine view type and handle accordingly
            view_type = ViewType.FUNCTION
            registered_view = view
            
            if hasattr(view, 'as_view'):
                # Class-based view
                view_type = ViewType.CLASS
            elif callable(view):
                # Function-based view - wrap it to preserve functionality
                @wraps(view)
                def wrapped_view(*args, **kwargs):
                    return view(*args, **kwargs)
                registered_view = wrapped_view
            else:
                raise TypeError("The provided view is neither a valid function-based view nor a class-based view.")
            
            # Create and store the route
            for model in _retrieve_models(models, exclude_models, RouteType(route_type)):
                # Generate name for this model/view combination
                actual_name = _generate_name(_name, model, registered_view)
                
                # Auto-generate description if not provided
                actual_description = _description
                if not actual_description:
                    if hasattr(view, '__doc__') and view.__doc__:
                        actual_description = view.__doc__.strip()
                    else:
                        actual_description = f"Route for {actual_name}"
                
                # Auto-generate path if not provided
                actual_path = _path
                if not actual_path:
                    if hasattr(view, '__name__'):
                        actual_path = f"/{view.__name__.replace('_', '-')}/"
                    elif hasattr(view, '__class__'):
                        actual_path = f"/{view.__class__.__name__.lower()}/"
                    else:
                        actual_path = "/unnamed-route/"
                
                # Auto-generate url_name if not provided
                actual_url_name = _url_name if _url_name else actual_name
                
                route = BloomerpRoute(
                    path=_generate_path(_path, RouteType(route_type), model),
                    model=model,
                    route_type=RouteType(route_type),
                    name=actual_name,
                    url_name=_auto_generate_url_name(actual_url_name, RouteType(route_type), model),
                    view=registered_view,
                    view_type=view_type,
                    description=_generate_description(description, model, registered_view),
                    override=override
                )
                
                self.routes.append(route)
            
            # Return the original view (for CBV) or wrapped view (for FBV)
            return view if view_type == 'class' else registered_view
            
        return decorator
    
    def get_routes(self) -> List[BloomerpRoute]:
        """Get all registered routes."""
        self._auto_import_views()  # Ensure views are imported before returning routes
        return self.routes.copy()
    
    def get_routes_by_model(self, model: Model) -> List[BloomerpRoute]:
        """Get all routes registered for a specific model."""
        self._auto_import_views()
        return [route for route in self.routes if route.model == model]
    
    def get_routes_by_type(self, route_type: str) -> List[BloomerpRoute]:
        """Get all routes of a specific type."""
        self._auto_import_views()
        return [route for route in self.routes if route.route_type == route_type]
    
    def get_function_based_routes(self) -> List[BloomerpRoute]:
        """Get all function-based view routes."""
        self._auto_import_views()
        return [route for route in self.routes if route.view_type == ViewType.FUNCTION]
    
    def get_class_based_routes(self) -> List[BloomerpRoute]:
        """Get all class-based view routes."""
        self._auto_import_views()
        return [route for route in self.routes if route.view_type == ViewType.CLASS]
    
    def create_url_patterns(self, prefix:Optional[str]=None):
        """
        Create Django URL patterns from registered routes.
        Returns a list of path() objects that can be used in urlpatterns.
        """
        self._auto_import_views()  # Ensure views are imported before creating patterns

        from django.urls import path as django_path
        
        patterns = []
        for route in self.routes:
            args = route.args if route.args else {}
            if route.model:
                args["model"] = route.model
            
            if route.view_type == ViewType.CLASS:
                # For class-based views, use as_view()
                pattern = django_path(
                    route.path.lstrip('/'), 
                    route.view.as_view(**args), 
                    name=route.url_name
                )
            else:
                # For function-based views, use the view directly
                pattern = django_path(
                    route.path.lstrip('/'), 
                    route.view, 
                    name=route.url_name,
                    kwargs=args
                )
            patterns.append(pattern)
        
        return patterns
    
    def clear_routes(self):
        """Clear all registered routes."""
        self.routes.clear()



# Global registry instance
router = BloomerpRouteRegistry(
    dirs=[
        "views",
        "components",
    ]
)
