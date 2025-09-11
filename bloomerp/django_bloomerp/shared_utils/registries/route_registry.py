from dataclasses import dataclass
from django.db.models import Model
from django.urls import path
from functools import wraps
from typing import List, Callable, Union
from enum import Enum
import os
import importlib
import glob
from django.conf import settings

class RouteType(Enum):
    APP = "app"
    LIST = "list"
    DETAIL = "detail"

@dataclass
class BloomerpRoute:
    path: str
    models: Union[Model, List[Model], str, None]
    route_type: str
    name: str
    view: Callable = None
    view_type: str = 'function'
    description: str = None
    override: bool = False


class BloomerpRouteRegistry:
    """
    A route registry for registering both function-based and class-based views
    with Django models using decorators.
    """
    
    def __init__(self):
        self.routes: List[BloomerpRoute] = []
        self._auto_imported = False
    
    def _auto_import_views(self):
        """
        Automatically import all Python files in the views directories
        to ensure route registrations are executed.
        """
        if self._auto_imported:
            return
            
        try:
            # Get all installed Django apps
            from django.apps import apps
            for app_config in apps.get_app_configs():
                app_path = app_config.path
                views_path = os.path.join(app_path, 'views')
                
                # Check if views directory exists
                if os.path.exists(views_path) and os.path.isdir(views_path):
                    # Find all Python files in views directory
                    pattern = os.path.join(views_path, '*.py')
                    view_files = glob.glob(pattern)
                    
                    for view_file in view_files:
                        if os.path.basename(view_file) == '__init__.py':
                            continue
                            
                        # Convert file path to module name
                        relative_path = os.path.relpath(view_file, app_path)
                        module_path = relative_path.replace(os.path.sep, '.').replace('.py', '')
                        module_name = f"{app_config.name}.{module_path}"
                        
                        try:
                            importlib.import_module(module_name)
                        except (ImportError, AttributeError, ModuleNotFoundError):
                            # Ignore import errors - some files might not be valid modules
                            pass
                
                # Also check for views.py file directly in the app
                views_file = os.path.join(app_path, 'views.py')
                if os.path.exists(views_file):
                    try:
                        importlib.import_module(f"{app_config.name}.views")
                    except (ImportError, AttributeError, ModuleNotFoundError):
                        pass
                        
            self._auto_imported = True
            
        except Exception:
            # If anything goes wrong, just continue - better to have some routes than none
            self._auto_imported = True
    
    def register(
        self, 
        path: str = None,
        models: Union[Model, List[Model], str, None] = None,
        route_type: str = 'app',
        name: str = None,
        description: str = None,
        override: bool = False
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
            nonlocal path, models, route_type, name, description, override
            
            # Auto-generate name if not provided
            if not name:
                if hasattr(view, '__name__'):
                    name = view.__name__.replace('_', ' ').title()
                elif hasattr(view, '__class__'):
                    name = view.__class__.__name__
                else:
                    name = 'Unnamed Route'
            
            # Auto-generate description if not provided
            if not description:
                if hasattr(view, '__doc__') and view.__doc__:
                    description = view.__doc__.strip()
                else:
                    description = f"Route for {name}"
            
            # Auto-generate path if not provided
            if not path:
                if hasattr(view, '__name__'):
                    path = f"/{view.__name__.replace('_', '-')}/"
                elif hasattr(view, '__class__'):
                    path = f"/{view.__class__.__name__.lower()}/"
                else:
                    path = "/unnamed-route/"
            
            # Ensure path starts and ends with /
            if not path.startswith('/'):
                path = '/' + path
            if not path.endswith('/'):
                path = path + '/'
            
            # Determine view type and handle accordingly
            view_type = 'function'
            registered_view = view
            
            if hasattr(view, 'as_view'):
                # Class-based view
                view_type = 'class'
            elif callable(view):
                # Function-based view - wrap it to preserve functionality
                @wraps(view)
                def wrapped_view(*args, **kwargs):
                    return view(*args, **kwargs)
                registered_view = wrapped_view
            else:
                raise TypeError("The provided view is neither a valid function-based view nor a class-based view.")
            
            # Create and store the route
            route = BloomerpRoute(
                path=path,
                models=models,
                route_type=route_type,
                name=name,
                view=registered_view,
                view_type=view_type,
                description=description,
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
        return [route for route in self.routes if route.models == model]
    
    def get_routes_by_type(self, route_type: str) -> List[BloomerpRoute]:
        """Get all routes of a specific type."""
        self._auto_import_views()
        return [route for route in self.routes if route.route_type == route_type]
    
    def get_function_based_routes(self) -> List[BloomerpRoute]:
        """Get all function-based view routes."""
        self._auto_import_views()
        return [route for route in self.routes if route.view_type == 'function']
    
    def get_class_based_routes(self) -> List[BloomerpRoute]:
        """Get all class-based view routes."""
        self._auto_import_views()
        return [route for route in self.routes if route.view_type == 'class']
    
    def create_url_patterns(self):
        """
        Create Django URL patterns from registered routes.
        Returns a list of path() objects that can be used in urlpatterns.
        """
        self._auto_import_views()  # Ensure views are imported before creating patterns
        
        from django.urls import path as django_path
        
        patterns = []
        for route in self.routes:
            if route.view_type == 'class':
                # For class-based views, use as_view()
                pattern = django_path(
                    route.path.lstrip('/'), 
                    route.view.as_view(), 
                    name=route.name.lower().replace(' ', '_')
                )
            else:
                # For function-based views, use the view directly
                pattern = django_path(
                    route.path.lstrip('/'), 
                    route.view, 
                    name=route.name.lower().replace(' ', '_')
                )
            patterns.append(pattern)
        
        return patterns
    
    def clear_routes(self):
        """Clear all registered routes."""
        self.routes.clear()


# Global registry instance
router = BloomerpRouteRegistry()
