from dataclasses import dataclass
from enum import Enum
from optparse import Option
from sre_constants import LITERAL
from django.views import View
from typing import Union
import logging
from typing import Optional
from django.db.models import Model
import importlib
import os
from functools import wraps
from typing import Callable, List, Literal

from regex import B
from bloomerp.modules.definition import ModuleConfig, module_registry
logger = logging.getLogger(__name__)

def _generate_description(
    name: Optional[str] = None,
    model: Optional[Model] = None,
    view: Optional[Callable | View] = None,
    module: Optional[ModuleConfig] = None,
) -> str:
    """Auto-generate a descriptive name including model information"""
    if not name and not model and not view and not module:
        raise Exception("At least one argument needs to be given")

    # If name is provided, handle it
    if name:
        format_values = {}
        if model:
            format_values["model"] = model._meta.verbose_name
        if module:
            format_values["module"] = module.name if getattr(module, "name", None) else module.id

        if "{" in name and format_values:
            try:
                return name.format(**format_values)
            except Exception:
                return name

        # Return name as-is if no formatting needed
        return name

    # If no name but we have model and view, generate from view name
    if not name and model and view:
        if hasattr(view, '__name__'):
            # Function-based view - convert snake_case to readable format
            view_name = view.__name__.replace('_', ' ')
            return view_name
        elif hasattr(view, '__class__'):
            # Class-based view - convert CamelCase to readable format
            class_name = view.__class__.__name__
            # Add spaces before capital letters and convert to lowercase
            import re
            readable_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', class_name)
            return readable_name

    # If we only have view (no name, no model), still try to generate from view
    if view and not name:
        if hasattr(view, '__name__'):
            return view.__name__.replace('_', ' ')
        elif hasattr(view, '__class__'):
            class_name = view.__class__.__name__
            import re
            readable_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', class_name)
            return readable_name

    # If we have model but no view and no name, we can't generate anything meaningful
    if model and not view and not name:
        raise Exception("Unable to generate name with provided arguments")

    # If nothing matches, raise error
    raise Exception("Unable to generate name with provided arguments")


def _generate_name(
    name: Optional[str] = None,
    model: Optional[Model] = None,
    view: Optional[Callable | View] = None,
    module: Optional[ModuleConfig] = None,
) -> str:
    """Auto-generate a descriptive name including model information"""
    if not name and not model and not view and not module:
        raise Exception("At least one argument needs to be given")

    # If name is provided, handle it
    if name:
        format_values = {}
        if model:
            format_values["model"] = model._meta.verbose_name
        if module:
            format_values["module"] = module.name if getattr(module, "name", None) else module.id

        if "{" in name and format_values:
            try:
                return name.format(**format_values)
            except Exception:
                return name

        # Return name as-is if no formatting needed
        return name

    # If no name but we have model and view, generate from view name
    if not name and model and view:
        if hasattr(view, '__name__'):
            # Function-based view - convert snake_case to readable format
            view_name = view.__name__.replace('_', ' ')
            return view_name
        elif hasattr(view, '__class__'):
            # Class-based view - convert CamelCase to readable format
            class_name = view.__class__.__name__
            # Add spaces before capital letters and convert to lowercase
            import re
            readable_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', class_name)
            return readable_name

    # If we only have view (no name, no model), still try to generate from view
    if view and not name:
        if hasattr(view, '__name__'):
            return view.__name__.replace('_', ' ')
        elif hasattr(view, '__class__'):
            class_name = view.__class__.__name__
            import re
            readable_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', class_name)
            return readable_name

    # If we have model but no view and no name, we can't generate anything meaningful
    if model and not view and not name:
        raise Exception("Unable to generate name with provided arguments")

    # If nothing matches, raise error
    raise Exception("Unable to generate name with provided arguments")


# ------------------------
# Data classes
# ------------------------
class RouteType(Enum):
    APP = "app"
    MODEL = "model"
    DETAIL = "detail"
    MODULE = "module"

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
    module: Optional[ModuleConfig] = None
    description: str = None
    override: bool = False
    args : Optional[dict] = None

    
    def nr_of_args(self) -> int:
        """Number of arguments the view takes (excluding 'request')"""
        # Each arg contains one "<"
        return self.path.count("<")
    
# ------------------------
# Helper functions
# ------------------------
def _retrieve_models(models:list[Model], exclude_models:list[Model], route_type: RouteType) -> list[Model]:
    """Retrieves the used models from the parameters"""
    if route_type in [RouteType.APP, RouteType.MODULE]:
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


def _generate_path(path: str, route_type: RouteType, model: Optional[Model] = None, module: Optional[ModuleConfig] = None) -> str:
    """Auto-generates a URL path based on the route type and model information."""
    # Validate that models are provided for routes that need them
    if route_type in [RouteType.DETAIL, RouteType.MODEL] and not model:
        raise ValueError(f"Model required for route type '{route_type.value}'")
    if route_type in [RouteType.DETAIL, RouteType.MODEL, RouteType.MODULE] and not module:
        raise ValueError(f"Module required for route type '{route_type.value}'")

    # Ensure path has proper slashes
    if path and not path.startswith('/'):
        path = '/' + path
    if path and not path.endswith('/'):
        path = path + '/'

    # Handle different route types
    if route_type == RouteType.APP:
        return path if path else "/app-route/"

    elif route_type == RouteType.MODULE:
        module_path = f"/{module.id.lower()}/"
        return module_path + path.lstrip('/') if path else module_path
    
    elif route_type == RouteType.MODEL:
        # Get model plural name and convert to URL-friendly format
        model_plural = model._meta.verbose_name_plural.lower().replace(' ', '-')
        if path:
            return f"/{module.id.lower()}/{model_plural}{path}"
        return f"/{module.id.lower()}/{model_plural}/"

    elif route_type == RouteType.DETAIL:
        # Get model plural name and convert to URL-friendly format
        model_name = model._meta.verbose_name_plural.lower().replace(' ', '-')
        if path:
            return f"/{module.id.lower()}/{model_name}/<int_or_uuid:pk>{path}"
        return f"/{module.id.lower()}/{model_name}/<int_or_uuid:pk>/"
    else:
        return path if path else "/auto-route/"


def _auto_generate_url_name(name: Optional[str], route_type: RouteType, model: Optional[Model] = None, module: Optional[ModuleConfig] = None) -> str:
    """Auto generates a url name based on the given parameters"""
    def _transform_str(value:str) -> str:
        if value is None:
            return "unnamed_route"
        return value.lower().replace(" ","_")

    if route_type in [RouteType.DETAIL, RouteType.MODEL] and model is None:
        raise ValueError(f"Model required for '{route_type.value}' route type")
    if route_type == RouteType.MODULE and module is None:
        raise ValueError("Module required for 'module' route type")

    match route_type:
        case RouteType.APP:
            return _transform_str(name)
        case RouteType.DETAIL:
            return _transform_str(model._meta.verbose_name_plural) + "_" + route_type.value + "_" + _transform_str(name)
        case RouteType.MODEL:
            return _transform_str(model._meta.verbose_name_plural) + "_" + _transform_str(name)
        case RouteType.MODULE:
            return _transform_str(module.id) + "_" + route_type.value + "_" + _transform_str(name)
        case _:
            raise ValueError("Invalid route type")


# ------------------------
# Main registry class
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
        # Stores registration parameters for MODEL/DETAIL routes so they can be
        # replayed for models that are created after the initial import (e.g. in tests).
        self._model_route_templates: List[dict] = []

    def route(self, *args, **kwargs):
        return self.register(*args, **kwargs)
    
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
                                    # Keep startup resilient, but surface route-load failures clearly.
                                    logger.warning(
                                        "Skipping auto-import for module '%s' due to import error: %s",
                                        module_name,
                                        e,
                                        exc_info=True,
                                    )
                                except Exception as e:
                                    logger.warning(
                                        "Skipping auto-import for module '%s' due to unexpected error: %s",
                                        module_name,
                                        e,
                                        exc_info=True,
                                    )


                    # Also check for direct file (e.g., views.py, components.py)
                    direct_file = os.path.join(app_path, f'{dir_name}.py')
                    if os.path.exists(direct_file):
                        try:
                            module_name = f"{app_config.name}.{dir_name}"
                            importlib.import_module(module_name)
                            logger.debug(f"Successfully imported: {module_name}")
                        except (ImportError, AttributeError, ModuleNotFoundError) as e:
                            logger.warning(
                                "Skipping auto-import for module '%s' due to import error: %s",
                                module_name,
                                e,
                                exc_info=True,
                            )
                        except Exception as e:
                            logger.warning(
                                "Skipping auto-import for module '%s' due to unexpected error: %s",
                                module_name,
                                e,
                                exc_info=True,
                            )

            self._auto_imported = True
            logger.info(f"Auto-import completed. Registered {len(self.routes)} routes.")

        except Exception as e:
            # If anything goes wrong, log it but continue - better to have some routes than none
            logger.error(f"Error during auto-import: {e}", exc_info=True)
            self._auto_imported = True

    def register(
        self,
        path: str = None,
        route_type: Literal['app', 'module', 'detail', 'model'] = 'app',
        models: Union[Model, List[Model], str, None] = None,
        modules: Union[ModuleConfig, List[ModuleConfig], str, None] = None,
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
            route_type: Type of route ('app', 'module', 'detail', 'model')
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
            _route_type = RouteType(route_type)
            _modules = modules
            
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
            
            def _auto_path() -> str:
                if _path:
                    return _path
                if hasattr(view, '__name__'):
                    return f"/{view.__name__.replace('_', '-')}/"
                if hasattr(view, '__class__'):
                    return f"/{view.__class__.__name__.lower()}/"
                return "/unnamed-route/"

            def _auto_description(actual_name: str) -> str:
                if _description:
                    return _description
                if hasattr(view, '__doc__') and view.__doc__:
                    return view.__doc__.strip()
                return f"Route for {actual_name}"

            match _route_type:
                case RouteType.APP:
                    if _modules or models or exclude_models:
                        raise ValueError("Modules and models parameters are not applicable for 'app' route type")

                    actual_name = _generate_name(_name, None, registered_view, None)
                    actual_description = _auto_description(actual_name)
                    actual_path = _auto_path()
                    actual_url_name = _url_name if _url_name else actual_name

                    self.routes.append(
                        BloomerpRoute(
                            path=_generate_path(actual_path, _route_type),
                            route_type=_route_type,
                            name=actual_name,
                            url_name=_auto_generate_url_name(actual_url_name, _route_type),
                            view=registered_view,
                            view_type=view_type,
                            module=None,
                            description=_generate_description(actual_description, None, registered_view, None),
                            override=override
                        )
                    )

                case RouteType.MODULE:
                    if _modules is None:
                        raise ValueError("Modules parameter is required for 'module' route type")

                    if _modules == "__all__":
                        modules_list = module_registry.get_all().values()
                    elif isinstance(_modules, ModuleConfig):
                        modules_list = [_modules]
                    elif isinstance(_modules, str):
                        modules_list = [module_registry.get(_modules)]
                    elif isinstance(_modules, list):
                        modules_list = _modules
                    else:
                        raise ValueError("Modules parameter must be a ModuleConfig instance, a list of ModuleConfig instances, or '__all__'")

                    for module in modules_list:
                        if not module:
                            raise ValueError("Module not found in registry")

                        actual_name = _generate_name(_name, None, registered_view, module)
                        actual_description = _auto_description(actual_name)
                        actual_path = _auto_path()
                        actual_url_name = _url_name if _url_name else actual_name

                        self.routes.append(
                            BloomerpRoute(
                                path=_generate_path(actual_path, _route_type, None, module),
                                route_type=_route_type,
                                name=actual_name,
                                url_name=_auto_generate_url_name(actual_url_name, _route_type, None, module),
                                view=registered_view,
                                view_type=view_type,
                                module=module,
                                description=_generate_description(actual_description, None, registered_view, module),
                                override=override
                            )
                        )

                case RouteType.MODEL | RouteType.DETAIL:
                    # Store template so late-arriving models can be registered later
                    self._model_route_templates.append({
                        'path': _auto_path(),
                        'route_type': _route_type,
                        'name': _name,
                        'description': _description,
                        'url_name': _url_name,
                        'override': override,
                        'view': view,
                        'view_type': view_type,
                        'registered_view': registered_view,
                    })

                    for model in _retrieve_models(models, exclude_models, _route_type):
                        actual_path = _auto_path()

                        modules_list = module_registry.get_modules_for_model(model) if model else []

                        for module in modules_list:
                            actual_name = _generate_name(_name, model, registered_view, module)
                            actual_description = _auto_description(actual_name)
                            actual_url_name = _url_name if _url_name else actual_name
                            route = BloomerpRoute(
                                path=_generate_path(actual_path, _route_type, model, module),
                                model=model,
                                module=module,
                                route_type=_route_type,
                                name=actual_name,
                                url_name=_auto_generate_url_name(actual_url_name, _route_type, model, module),
                                view=registered_view,
                                view_type=view_type,
                                description=_generate_description(actual_description, model, registered_view, module),
                                override=override
                            )

                            self.routes.append(route)
   
            # Return the original view (for CBV) or wrapped view (for FBV)
            return view if view_type == ViewType.CLASS else registered_view

        return decorator

    def register_routes_for_model(self, model: Model) -> None:
        """
        Register all stored model-route templates for the given model.

        This is useful when a model is created after the initial import (e.g.
        dynamic test models created in ``setUpClass``). Call this after adding
        the model to Django's app registry and to the module_registry so that
        route paths and URL names are generated correctly.
        """
        self._auto_import_views()  # Ensure templates are populated

        existing_url_names = {r.url_name for r in self.routes}

        for template in self._model_route_templates:
            modules_list = module_registry.get_modules_for_model(model)
            for module in modules_list:
                actual_path = template['path']
                actual_name = _generate_name(template['name'], model, template['view'], module)

                def _auto_desc(name: str, tmpl: dict = template) -> str:
                    if tmpl['description']:
                        return tmpl['description']
                    view = tmpl['view']
                    if hasattr(view, '__doc__') and view.__doc__:
                        return view.__doc__.strip()
                    return f"Route for {name}"

                actual_description = _auto_desc(actual_name)
                actual_url_name_raw = template['url_name'] if template['url_name'] else actual_name
                url_name = _auto_generate_url_name(actual_url_name_raw, template['route_type'], model, module)

                # Skip if already registered (idempotent)
                if url_name in existing_url_names:
                    continue

                route = BloomerpRoute(
                    path=_generate_path(actual_path, template['route_type'], model, module),
                    model=model,
                    module=module,
                    route_type=template['route_type'],
                    name=actual_name,
                    url_name=url_name,
                    view=template['registered_view'],
                    view_type=template['view_type'],
                    description=_generate_description(actual_description, model, template['view'], module),
                    override=template['override'],
                )
                self.routes.append(route)
                existing_url_names.add(url_name)

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
            
            if route.module:
                args["module"] = route.module

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

    def filter(
        self,
        route_type: Optional[Literal['app', 'model', 'module', 'detail']] | Optional[RouteType] = None,
        model: Optional[Model] = None,
        module: Optional[ModuleConfig] = None,
        view_type: Optional[str] | Optional[ViewType] = None,
        name_contains: Optional[str] = None,
        description_contains: Optional[str] = None,
    ) -> list[BloomerpRoute]:
        """
        Filter registered routes and return a list of matching `BloomerpRoute` objects.

        The registry will auto-import configured view modules before filtering to
        ensure all registered routes are available.

        Args
        - `route_type`: Optional; a `RouteType` enum or its string value
            (e.g. 'app', 'module', 'model', 'detail'). If provided only routes
            of that type are returned.
        - `model`: Optional Django `Model` class. If provided only routes
            associated with that model are returned.
        - `module`: Optional `ModuleConfig`. If provided only routes for that
            module are returned.
        - `view_type`: Optional; a `ViewType` enum or its string value
            ('class' or 'function'). If provided only routes of that view type
            are returned.
        - `name_contains`: Optional string. Case-insensitive substring match
            against the route `name`.
        - `description_contains`: Optional string. Case-insensitive substring
            match against the route `description`.

        Returns
        - `list[BloomerpRoute]`: List of routes matching all provided filters.
        """
        self._auto_import_views()

        resolved_route_type = None
        if route_type is not None:
            if isinstance(route_type, RouteType):
                resolved_route_type = route_type
            else:
                try:
                    resolved_route_type = RouteType(str(route_type))
                except ValueError:
                    resolved_route_type = None

        resolved_view_type = None
        if view_type is not None:
            if isinstance(view_type, ViewType):
                resolved_view_type = view_type
            else:
                try:
                    resolved_view_type = ViewType(str(view_type))
                except ValueError:
                    resolved_view_type = None

        name_query = name_contains.lower() if name_contains else None
        description_query = description_contains.lower() if description_contains else None

        results: list[BloomerpRoute] = []
        for route in self.routes:
            if resolved_route_type is not None and route.route_type != resolved_route_type:
                continue

            if resolved_view_type is not None and route.view_type != resolved_view_type:
                continue

            if model is not None and route.model != model:
                continue

            if module is not None and route.module != module:
                continue

            if name_query:
                route_name = route.name or ""
                if name_query not in route_name.lower():
                    continue

            if description_query:
                route_description = route.description or ""
                if description_query not in route_description.lower():
                    continue

            results.append(route)

        return results
    

# ------------------------
# Init router
# ------------------------
# TODO: Consider making this a singleton if we want to ensure only one instance exists across the app. For now, we can just use a single instance in the router variable.
# TODO: Consider importing the dirs from settings.py
router = BloomerpRouteRegistry(
    dirs=[
        "views",
        "components",
    ]
)

