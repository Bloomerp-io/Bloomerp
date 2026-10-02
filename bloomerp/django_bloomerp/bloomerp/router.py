from dataclasses import dataclass
from enum import Enum
from django.views import View
from django.apps import AppConfig, apps
from django.utils.encoding import force_str
from django.utils.translation import gettext, pgettext
from typing import Union
import logging
from typing import Optional
from django.db.models import Model
import importlib
import os
import re
from functools import wraps
from typing import Any, Callable, List, Literal

from bloomerp.mcp.definition import McpTool
from bloomerp.models.definition import get_model_config
from bloomerp.i18n.models import model_verbose_name_in_source_language
from bloomerp.modules.definition import BloomerpModule, ModuleConfig, module_registry
logger = logging.getLogger(__name__)

MCP_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

def _generate_description(
    name: Optional[str] = None,
    model: Optional[Model] = None,
    view: Optional[Callable | View] = None,
    module: Optional[ModuleConfig] = None,
    message_format_values: Optional[dict[str, object]] = None,
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
        format_values.update(message_format_values or {})

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
    message_format_values: Optional[dict[str, object]] = None,
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
        format_values.update(message_format_values or {})

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
    API = "api"
    API_MODEL = "api_model"
    API_DETAIL = "api_detail"
    WEBSOCKET = "websocket"
    MCP = "mcp"

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
    name_message: Optional[str] = None
    description_message: Optional[str] = None
    owner_app_label: Optional[str] = None
    translatable: bool = True
    searchable: bool = True
    message_format_values: Optional[dict[str, object]] = None
    re_path: Optional[str] = None
    base_url_name: Optional[str] = None
    mcp: Optional[McpTool] = None

    @property
    def mcp_tool_name(self) -> Optional[str]:
        """Return the route-derived MCP tool name when MCP is enabled."""
        if self.mcp is None:
            return None
        return self.url_name

    def _translation_context(self, field: str) -> str:
        owner = self.owner_app_label or "bloomerp"
        return f"{owner}:route:{field}"

    def _localized_message(self, message: Optional[str], field: str) -> str:
        if not message:
            return ""
        translated = message
        if self.translatable:
            translated = pgettext(self._translation_context(field), message)
            if translated == message:
                # Reuse existing context-free catalogs while route-specific
                # contextual entries are introduced and translated.
                translated = gettext(message)
        values = {}
        if self.model is not None:
            values["model"] = force_str(self.model._meta.verbose_name)
        if self.module is not None:
            values["module"] = force_str(
                self.module.localized_name
                if getattr(self.module, "name", None)
                else self.module.id
            )
        values.update(
            {
                key: force_str(value)
                for key, value in (self.message_format_values or {}).items()
            }
        )
        if values and "{" in translated:
            try:
                return translated.format(**values)
            except (KeyError, ValueError):
                pass
        return translated

    @property
    def localized_name(self) -> str:
        message = self.name if self.name_message is None else self.name_message
        return self._localized_message(message, "name")

    @property
    def localized_description(self) -> str:
        message = (
            self.description
            if self.description_message is None
            else self.description_message
        )
        return self._localized_message(
            message,
            "description",
        )

    
    def nr_of_args(self) -> int:
        """Number of arguments the view takes (excluding 'request')"""
        if self.re_path is not None:
            return 0
        # Each arg contains one "<"
        return self.path.count("<")
    
# ------------------------
# Helper functions
# ------------------------
def _resolve_model_selector(selector):
    """Evaluate a deferred model selector without calling model classes."""
    if callable(selector) and not (
        isinstance(selector, type) and issubclass(selector, Model)
    ):
        return selector()
    return selector


def _retrieve_models(models, exclude_models, route_type: RouteType) -> list[Model]:
    """Retrieves the used models from the parameters"""
    if route_type in [RouteType.APP, RouteType.MODULE, RouteType.API]:
        return [None]  # App routes don't need models

    models = _resolve_model_selector(models)
    exclude_models = _resolve_model_selector(exclude_models)
    
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


def _is_model_route(route_type: RouteType) -> bool:
    return route_type in {
        RouteType.MODEL,
        RouteType.DETAIL,
        RouteType.API_MODEL,
        RouteType.API_DETAIL,
    }


def _is_module_model_route(route_type: RouteType) -> bool:
    return route_type in {RouteType.MODEL, RouteType.DETAIL}


def _is_api_route(route_type: RouteType) -> bool:
    return route_type in {
        RouteType.API,
        RouteType.API_MODEL,
        RouteType.API_DETAIL,
    }


def _is_websocket_route(route_type: RouteType) -> bool:
    return route_type == RouteType.WEBSOCKET


def _get_api_model_path(model: Model) -> str:
    return model_verbose_name_in_source_language(model, plural=True).replace(" ", "_").lower()


def _with_api_prefix(path: Optional[str], default_path: str = "") -> str:
    raw_path = path if path else default_path
    raw_path = str(raw_path or "").strip("/")

    if not raw_path:
        return "/api/"
    if raw_path == "api" or raw_path.startswith("api/"):
        return f"/{raw_path}/"
    return f"/api/{raw_path}/"


def _generate_path(path: str, route_type: RouteType, model: Optional[Model] = None, module: Optional[ModuleConfig] = None) -> str:
    """Auto-generates a URL path based on the route type and model information."""
    # Validate that models are provided for routes that need them
    if _is_model_route(route_type) and not model:
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
        module_path = f"/{(module.route_path or module.id.lower()).strip('/')}/"
        return module_path + path.lstrip('/') if path else module_path
    
    elif route_type == RouteType.MODEL:
        # Get model plural name and convert to URL-friendly format
        model_plural = model_verbose_name_in_source_language(model, plural=True).lower().replace(' ', '-')
        module_path = (module.route_path or module.id.lower()).strip("/")
        if path:
            return f"/{module_path}/{model_plural}{path}"
        return f"/{module_path}/{model_plural}/"

    elif route_type == RouteType.DETAIL:
        # Get model plural name and convert to URL-friendly format
        model_name = model_verbose_name_in_source_language(model, plural=True).lower().replace(' ', '-')
        module_path = (module.route_path or module.id.lower()).strip("/")
        if path:
            return f"/{module_path}/{model_name}/<int_or_uuid:pk>{path}"
        return f"/{module_path}/{model_name}/<int_or_uuid:pk>/"
    elif route_type == RouteType.API:
        return _with_api_prefix(path, "auto-route")

    elif route_type == RouteType.API_MODEL:
        model_path = _get_api_model_path(model)
        if path:
            return _with_api_prefix(f"{model_path}{path}")
        return _with_api_prefix(model_path)

    elif route_type == RouteType.API_DETAIL:
        model_path = _get_api_model_path(model)
        if path:
            return _with_api_prefix(f"{model_path}/<int_or_uuid:pk>{path}")
        return _with_api_prefix(f"{model_path}/<int_or_uuid:pk>")
    else:
        return path if path else "/auto-route/"


def _auto_generate_url_name(name: Optional[str], route_type: RouteType, model: Optional[Model] = None, module: Optional[ModuleConfig] = None) -> str:
    """Auto generates a url name based on the given parameters"""
    def _transform_str(value:str) -> str:
        if value is None:
            return "unnamed_route"
        return value.lower().replace(" ","_")

    if _is_model_route(route_type) and model is None:
        raise ValueError(f"Model required for '{route_type.value}' route type")
    if route_type == RouteType.MODULE and module is None:
        raise ValueError("Module required for 'module' route type")

    match route_type:
        case RouteType.APP:
            return _transform_str(name)
        case RouteType.API:
            return _transform_str(name)
        case RouteType.WEBSOCKET:
            return _transform_str(name)
        case RouteType.MCP:
            return _transform_str(name)
        case RouteType.API_MODEL:
            model_path = _get_api_model_path(model)
            return f"{model_path}-list" if name is None else _transform_str(name)
        case RouteType.API_DETAIL:
            model_path = _get_api_model_path(model)
            return f"{model_path}-detail" if name is None else _transform_str(name)
        case RouteType.DETAIL:
            model_name = model_verbose_name_in_source_language(model, plural=True)
            return _transform_str(model_name) + "_" + route_type.value + "_" + _transform_str(name)
        case RouteType.MODEL:
            model_name = model_verbose_name_in_source_language(model, plural=True)
            return _transform_str(model_name) + "_" + _transform_str(name)
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

    def _routes_conflict(self, existing: BloomerpRoute, incoming: BloomerpRoute) -> bool:
        """Detect conflicting routes without treating all pathless MCP tools alike."""
        if existing.route_type != incoming.route_type:
            return False
        if incoming.route_type == RouteType.MCP:
            return existing.url_name == incoming.url_name
        if existing.model != incoming.model:
            return False
        if existing.module != incoming.module:
            return False
        return (
            existing.path == incoming.path
            and existing.re_path == incoming.re_path
        ) or existing.url_name == incoming.url_name

    def _add_route(self, route: BloomerpRoute) -> bool:
        conflicting_routes = [
            existing
            for existing in self.routes
            if self._routes_conflict(existing, route)
        ]

        if route.override:
            remaining_routes = [
                existing
                for existing in self.routes
                if not self._routes_conflict(existing, route)
            ]
            self._validate_mcp_route(route, routes=remaining_routes)
            self.routes = remaining_routes
            self.routes.append(route)
            return True

        if any(existing.override for existing in conflicting_routes):
            return False

        self._validate_mcp_route(route)
        self.routes.append(route)
        return True

    def _validate_mcp_route(
        self,
        route: BloomerpRoute,
        *,
        routes: Optional[List[BloomerpRoute]] = None,
    ) -> None:
        """Validate MCP route types and server-wide tool-name uniqueness."""
        if route.mcp is None:
            if route.route_type == RouteType.MCP:
                raise ValueError("MCP-only routes require an MCP contract")
            return

        if not (_is_api_route(route.route_type) or route.route_type == RouteType.MCP):
            raise ValueError(
                "MCP tools can only be attached to API routes or MCP-only routes"
            )
        if route.route_type != RouteType.MCP and (
            route.nr_of_args() or route.re_path is not None
        ):
            raise ValueError(
                "MCP API routes cannot require URL arguments or use re_path"
            )

        tool_name = route.mcp_tool_name
        if tool_name is None or MCP_TOOL_NAME_PATTERN.fullmatch(tool_name) is None:
            raise ValueError(
                "MCP tool names must be 1-128 characters and contain only "
                "letters, numbers, underscores, hyphens, or dots"
            )

        existing_routes = self.routes if routes is None else routes
        if any(
            existing.mcp is not None
            and existing.mcp_tool_name == tool_name
            for existing in existing_routes
        ):
            raise ValueError(f"Duplicate MCP tool name: {tool_name}")

    def route(self, *args, **kwargs):
        return self.register(*args, **kwargs)

    def _import_module(self, module_name: str) -> None:
        """Import a module while keeping route loading resilient."""
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
                            # Import package __init__.py modules as well so projects can
                            # register routes from views/__init__.py or components/__init__.py.
                            if '__init__.py' in files:
                                package_relative_path = os.path.relpath(root, app_path)
                                package_module_path = package_relative_path.replace(os.path.sep, '.')
                                module_name = f"{app_config.name}.{package_module_path}"
                                self._import_module(module_name)

                            for file in files:
                                if not file.endswith('.py') or file == '__init__.py':
                                    continue

                                file_path = os.path.join(root, file)

                                # Convert file path to module name
                                relative_path = os.path.relpath(file_path, app_path)
                                module_path = relative_path.replace(os.path.sep, '.').replace('.py', '')
                                module_name = f"{app_config.name}.{module_path}"
                                self._import_module(module_name)


                    # Also check for direct file (e.g., views.py, components.py)
                    direct_file = os.path.join(app_path, f'{dir_name}.py')
                    if os.path.exists(direct_file):
                        module_name = f"{app_config.name}.{dir_name}"
                        self._import_module(module_name)

            self._auto_imported = True
            logger.info(f"Auto-import completed. Registered {len(self.routes)} routes.")

        except Exception as e:
            # If anything goes wrong, log it but continue - better to have some routes than none
            logger.error(f"Error during auto-import: {e}", exc_info=True)
            self._auto_imported = True

    def register(
        self,
        path: str = None,
        re_path: Optional[str] = None,
        route_type: Literal['app', 'module', 'detail', 'model', 'api', 'api_model', 'api_detail', 'websocket', 'mcp'] | RouteType | None = None,
        models: Union[Model, List[Model], str, None] = None,
        modules: Union[BloomerpModule, List[BloomerpModule], str, None] = None,
        exclude_models:Union[Model, List[Model], str, None] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        url_name: Optional[str] = None,
        override: bool = False,
        translatable: Optional[bool] = None,
        searchable: Optional[bool] = None,
        message_format_values: Optional[dict[str, object]] = None,
        mcp: Optional[McpTool] = None,
    ) -> Callable[[Callable[..., Any] | type[View]], Callable[..., Any] | type[View]]:
        """
        Decorator for registering routes with the registry.
        Works for both function-based and class-based views.

        Args:
            path: A Django ``path()`` pattern (optional, auto-generated if omitted)
            re_path: A complete Django ``re_path()`` regular expression
            models: The model(s) associated with this route
            route_type: Type of route ('app', 'module', 'detail', 'model', 'api', 'api_model', 'api_detail')
            name: Name for the route (optional, derived from view if not provided)
            description: Description of the route
            override: Whether to override existing routes with same path
            mcp: Optional MCP tool contract. Without a path or route type, this
                selects an MCP-only route with no Django URL pattern.
        """
        def decorator(view: Callable[..., Any] | type[View]) -> Callable[..., Any] | type[View]:
            """Register the decorated view and preserve its original interface."""
            if path is not None and re_path is not None:
                raise ValueError("Only one of 'path' or 're_path' may be provided")

            # Use local variables to avoid nonlocal complications
            _name = name
            _description = description
            _path = path
            _re_path = re_path
            _url_name = url_name
            selected_type = route_type or (
                RouteType.MCP if mcp is not None and path is None and re_path is None
                else RouteType.APP
            )
            _route_type = selected_type if isinstance(selected_type, RouteType) else RouteType(str(selected_type).lower())
            _modules = modules

            if _route_type == RouteType.MCP and (_path is not None or _re_path is not None):
                raise ValueError("MCP-only routes cannot define a URL path")

            if _is_websocket_route(_route_type) and not hasattr(view, 'as_asgi'):
                raise TypeError(
                    "Websocket routes must use a Channels consumer with an 'as_asgi' method"
                )

            owner_app = apps.get_containing_app_config(getattr(view, "__module__", ""))

            def _route_metadata(
                actual_path: str,
                actual_url_name: str,
                actual_name: str,
                actual_description: str,
            ) -> dict[str, Any]:
                """Build shared metadata for the route being registered."""
                is_component = (
                    actual_path.lstrip("/").startswith("components/")
                    or actual_url_name.startswith("components_")
                )
                is_api = _is_api_route(_route_type) or _route_type == RouteType.MCP
                should_translate = (
                    translatable
                    if translatable is not None
                    else not is_component and not is_api
                )
                should_search = (
                    searchable
                    if searchable is not None
                    else not is_component and not is_api
                )
                return {
                    "base_url_name": _url_name or _name or actual_url_name,
                    "name_message": _name or actual_name,
                    "description_message": _description,
                    "owner_app_label": owner_app.label if owner_app else None,
                    "translatable": should_translate,
                    "searchable": should_search,
                    "message_format_values": message_format_values,
                    "mcp": mcp,
                }
            
            # Determine view type and handle accordingly
            view_type = ViewType.FUNCTION
            registered_view = view

            if hasattr(view, 'as_view') or hasattr(view, 'as_asgi'):
                # Class-based view
                view_type = ViewType.CLASS
            elif callable(view):
                # Function-based view - wrap it to preserve functionality
                @wraps(view)
                def wrapped_view(*args: Any, **kwargs: Any) -> Any:
                    """Preserve function-view metadata while forwarding the call."""
                    return view(*args, **kwargs)
                registered_view = wrapped_view
            else:
                raise TypeError("The provided view is neither a valid function-based view nor a class-based view.")
            
            def _auto_path() -> str:
                """Derive the route path from the decorator or view name."""
                if _re_path is not None:
                    return _re_path
                if _path is not None:
                    return _path
                if hasattr(view, '__name__'):
                    return f"/{view.__name__.replace('_', '-')}/"
                if hasattr(view, '__class__'):
                    return f"/{view.__class__.__name__.lower()}/"
                return "/unnamed-route/"

            def _auto_description(actual_name: str) -> str:
                """Derive a human-facing route description."""
                if _description:
                    return _description
                if hasattr(view, '__doc__') and view.__doc__:
                    return view.__doc__.strip()
                return f"Route for {actual_name}"

            def _resolved_path(
                actual_path: str,
                model: Model | None = None,
                module: ModuleConfig | None = None,
            ) -> str:
                """Expand route-relative paths into their final URL paths."""
                if _re_path is not None:
                    return actual_path
                return _generate_path(actual_path, _route_type, model, module)

            match _route_type:
                case RouteType.MCP:
                    if _modules or models or exclude_models:
                        raise ValueError("MCP-only routes cannot specify modules or models")
                    if mcp is None:
                        raise ValueError("MCP-only routes require an MCP contract")
                    actual_name = _generate_name(
                        _name, None, registered_view, None, message_format_values
                    )
                    actual_description = _auto_description(actual_name)
                    actual_url_name = _url_name or actual_name
                    generated_url_name = _auto_generate_url_name(actual_url_name, _route_type)
                    self._add_route(
                        BloomerpRoute(
                            path="",
                            route_type=_route_type,
                            name=actual_name,
                            url_name=generated_url_name,
                            view=registered_view,
                            view_type=view_type,
                            description=actual_description,
                            override=override,
                            **_route_metadata(
                                "", generated_url_name, actual_name, actual_description
                            ),
                        )
                    )

                case RouteType.APP:
                    if _modules or models or exclude_models:
                        raise ValueError("Modules and models parameters are not applicable for 'app' route type")

                    actual_name = _generate_name(
                        _name,
                        None,
                        registered_view,
                        None,
                        message_format_values,
                    )
                    actual_description = _auto_description(actual_name)
                    actual_path = _auto_path()
                    actual_url_name = _url_name if _url_name else actual_name
                    generated_url_name = _auto_generate_url_name(actual_url_name, _route_type)

                    self._add_route(
                        BloomerpRoute(
                            path=_resolved_path(actual_path),
                            re_path=_re_path,
                            route_type=_route_type,
                            name=actual_name,
                            url_name=generated_url_name,
                            view=registered_view,
                            view_type=view_type,
                            module=None,
                            description=_generate_description(
                                actual_description,
                                None,
                                registered_view,
                                None,
                                message_format_values,
                            ),
                            override=override,
                            **_route_metadata(
                                actual_path,
                                generated_url_name,
                                actual_name,
                                actual_description,
                            ),
                        )
                    )

                case RouteType.MODULE:
                    if _modules is None:
                        raise ValueError("Modules parameter is required for 'module' route type")

                    if _modules == "__all__":
                        modules_list = module_registry.get_all().values()
                    elif type(_modules) == BloomerpModule:
                        modules_list = [_modules]
                    elif isinstance(_modules, str):
                        modules_list = [module_registry.get(_modules)]
                    elif isinstance(_modules, list):
                        modules_list = _modules
                    else:
                        raise ValueError("Modules parameter must be a BloomerpModule instance, a list of BloomerpModule instances, or '__all__'")

                    for module in modules_list:
                        if not module:
                            raise ValueError("Module not found in registry")

                        actual_name = _generate_name(
                            _name,
                            None,
                            registered_view,
                            module,
                            message_format_values,
                        )
                        actual_description = _auto_description(actual_name)
                        actual_path = _auto_path()
                        actual_url_name = _url_name if _url_name else actual_name
                        generated_url_name = _auto_generate_url_name(
                            actual_url_name,
                            _route_type,
                            None,
                            module,
                        )

                        self._add_route(
                            BloomerpRoute(
                                path=_resolved_path(actual_path, None, module),
                                re_path=_re_path,
                                route_type=_route_type,
                                name=actual_name,
                                url_name=generated_url_name,
                                view=registered_view,
                                view_type=view_type,
                                module=module,
                                description=_generate_description(
                                    actual_description,
                                    None,
                                    registered_view,
                                    module,
                                    message_format_values,
                                ),
                                override=override,
                                **_route_metadata(
                                    actual_path,
                                    generated_url_name,
                                    actual_name,
                                    actual_description,
                                ),
                            )
                        )

                case RouteType.MODEL | RouteType.DETAIL | RouteType.API_MODEL | RouteType.API_DETAIL:
                    # Store template so late-arriving models can be registered later
                    self._model_route_templates.append({
                        'path': _auto_path(),
                        're_path': _re_path,
                        'route_type': _route_type,
                        'name': _name,
                        'description': _description,
                        'url_name': _url_name,
                        'override': override,
                        'translatable': translatable,
                        'searchable': searchable,
                        'message_format_values': message_format_values,
                        'mcp': mcp,
                        'models': models,
                        'exclude_models': exclude_models,
                        'view': view,
                        'view_type': view_type,
                        'registered_view': registered_view,
                    })

                    for model in _retrieve_models(models, exclude_models, _route_type):
                        if model is None:
                            continue

                        config = get_model_config(model)
                        
                        # Skip for detail view
                        if _route_type == RouteType.DETAIL and config and config.detail_view_settings and config.detail_view_settings.skip_views:
                            if _url_name in config.detail_view_settings.skip_views:
                                continue
                            
                        if _route_type == RouteType.MODEL and config and config.model_view_settings and config.model_view_settings.skip_views:
                            if _url_name in config.model_view_settings.skip_views:
                                continue
                        
                        actual_path = _auto_path()

                        module = module_registry.get_module_for_model(model) if _is_module_model_route(_route_type) else None
                        if _is_module_model_route(_route_type) and not module:
                            continue

                        actual_name = _generate_name(
                            _name,
                            model,
                            registered_view,
                            module,
                            message_format_values,
                        )
                        actual_description = _auto_description(actual_name)
                        actual_url_name = _url_name if _url_name else (
                            _name if _is_api_route(_route_type) else actual_name
                        )
                        generated_path = _resolved_path(actual_path, model, module)
                        generated_url_name = _auto_generate_url_name(
                            actual_url_name,
                            _route_type,
                            model,
                            module,
                        )
                        route = BloomerpRoute(
                            path=generated_path,
                            re_path=_re_path,
                            model=model,
                            module=module,
                            route_type=_route_type,
                            name=actual_name,
                            url_name=generated_url_name,
                            view=registered_view,
                            view_type=view_type,
                            description=_generate_description(
                                actual_description,
                                model,
                                registered_view,
                                module,
                                message_format_values,
                            ),
                            override=override,
                            **_route_metadata(
                                generated_path,
                                generated_url_name,
                                actual_name,
                                actual_description,
                            ),
                        )

                        self._add_route(route)

                case RouteType.API:
                    if _modules or models or exclude_models:
                        raise ValueError("Modules and models parameters are not applicable for 'api' route type")

                    actual_name = _generate_name(
                        _name,
                        None,
                        registered_view,
                        None,
                        message_format_values,
                    )
                    actual_description = _auto_description(actual_name)
                    actual_path = _auto_path()
                    actual_url_name = _url_name if _url_name else actual_name
                    generated_url_name = _auto_generate_url_name(actual_url_name, _route_type)

                    self._add_route(
                        BloomerpRoute(
                            path=_resolved_path(actual_path),
                            re_path=_re_path,
                            route_type=_route_type,
                            name=actual_name,
                            url_name=generated_url_name,
                            view=registered_view,
                            view_type=view_type,
                            module=None,
                            description=_generate_description(
                                actual_description,
                                None,
                                registered_view,
                                None,
                                message_format_values,
                            ),
                            override=override,
                            **_route_metadata(
                                actual_path,
                                generated_url_name,
                                actual_name,
                                actual_description,
                            ),
                        )
                    )

                case RouteType.WEBSOCKET:
                    if _modules or models or exclude_models:
                        raise ValueError(
                            "Modules and models parameters are not applicable for 'websocket' route type"
                        )

                    actual_name = _generate_name(
                        _name,
                        None,
                        registered_view,
                        None,
                        message_format_values,
                    )
                    actual_description = _auto_description(actual_name)
                    actual_path = _auto_path()
                    actual_url_name = _url_name if _url_name else actual_name
                    generated_url_name = _auto_generate_url_name(actual_url_name, _route_type)

                    self._add_route(
                        BloomerpRoute(
                            path=_resolved_path(actual_path),
                            re_path=_re_path,
                            route_type=_route_type,
                            name=actual_name,
                            url_name=generated_url_name,
                            view=registered_view,
                            view_type=view_type,
                            module=None,
                            description=_generate_description(
                                actual_description,
                                None,
                                registered_view,
                                None,
                                message_format_values,
                            ),
                            override=override,
                            **_route_metadata(
                                actual_path,
                                generated_url_name,
                                actual_name,
                                actual_description,
                            ),
                        )
                    )

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

        for template in self._model_route_templates:
            if not self._template_applies_to_model(template, model):
                continue

            route_type = template['route_type']
            module = module_registry.get_module_for_model(model) if _is_module_model_route(route_type) else None
            if _is_module_model_route(route_type) and not module:
                continue

            actual_path = template['path']
            actual_name = _generate_name(
                template['name'],
                model,
                template['view'],
                module,
                template.get('message_format_values'),
            )

            def _auto_desc(name: str, tmpl: dict = template) -> str:
                if tmpl['description']:
                    return tmpl['description']
                view = tmpl['view']
                if hasattr(view, '__doc__') and view.__doc__:
                    return view.__doc__.strip()
                return f"Route for {name}"

            actual_description = _auto_desc(actual_name)
            actual_url_name_raw = template['url_name'] if template['url_name'] else (
                template['name'] if _is_api_route(route_type) else actual_name
            )
            url_name = _auto_generate_url_name(actual_url_name_raw, route_type, model, module)
            generated_path = (
                actual_path
                if template.get('re_path') is not None
                else _generate_path(actual_path, route_type, model, module)
            )
            owner_app = apps.get_containing_app_config(
                getattr(template['view'], "__module__", "")
            )
            is_component = (
                generated_path.lstrip("/").startswith("components/")
                or url_name.startswith("components_")
            )
            is_api = _is_api_route(route_type)
            translatable = template['translatable']
            searchable = template['searchable']

            route = BloomerpRoute(
                path=generated_path,
                re_path=template.get('re_path'),
                model=model,
                module=module,
                route_type=route_type,
                name=actual_name,
                url_name=url_name,
                view=template['registered_view'],
                view_type=template['view_type'],
                description=_generate_description(
                    actual_description,
                    model,
                    template['view'],
                    module,
                    template.get('message_format_values'),
                ),
                override=template['override'],
                base_url_name=(
                    template['url_name']
                    or template['name']
                    or actual_url_name_raw
                ),
                name_message=template['name'] or actual_name,
                description_message=template['description'],
                owner_app_label=owner_app.label if owner_app else None,
                translatable=(
                    translatable
                    if translatable is not None
                    else not is_component and not is_api
                ),
                searchable=(
                    searchable
                    if searchable is not None
                    else not is_component and not is_api
                ),
                message_format_values=template.get('message_format_values'),
                mcp=template.get('mcp'),
            )
            self._add_route(route)

    def _template_applies_to_model(self, template: dict, model: Model) -> bool:
        models = template.get('models')
        exclude_models = template.get('exclude_models')

        if models == "__all__":
            return not self._model_matches_selector(model, exclude_models)

        if models:
            return self._model_matches_selector(model, models)

        if exclude_models:
            return not self._model_matches_selector(model, exclude_models)

        return False

    def _model_matches_selector(self, model: Model, selector) -> bool:
        selector = _resolve_model_selector(selector)
        if not selector:
            return False

        if selector == "__all__":
            return True

        if isinstance(selector, list):
            return any(self._model_matches_selector(model, item) for item in selector)

        return selector is model

    def get_routes(self) -> List[BloomerpRoute]:
        """Get all registered routes."""
        self._auto_import_views()  # Ensure views are imported before returning routes
        return self.routes.copy()

    def get_routes_by_model(self, model: Model) -> List[BloomerpRoute]:
        """Get all routes registered for a specific model."""
        self._auto_import_views()
        return [route for route in self.routes if route.model == model]

    def get_mcp_routes(self) -> List[BloomerpRoute]:
        """Return MCP-enabled routes in deterministic tool-name order."""
        self._auto_import_views()
        return sorted(
            (route for route in self.routes if route.mcp is not None),
            key=lambda route: route.mcp_tool_name or "",
        )

    def get_routes_by_app(self, app: AppConfig) -> List[BloomerpRoute]:
        """Get all routes owned by a specific Django app."""
        self._auto_import_views()
        return [route for route in self.routes if route.owner_app_label == app.label]

    def get_routes_by_type(self, route_type: str | RouteType) -> List[BloomerpRoute]:
        """Get all routes of a specific type."""
        self._auto_import_views()
        resolved_route_type = route_type if isinstance(route_type, RouteType) else RouteType(str(route_type).lower())
        return [route for route in self.routes if route.route_type == resolved_route_type]

    def get_function_based_routes(self) -> List[BloomerpRoute]:
        """Get all function-based view routes."""
        self._auto_import_views()
        return [route for route in self.routes if route.view_type == ViewType.FUNCTION]

    def get_class_based_routes(self) -> List[BloomerpRoute]:
        """Get all class-based view routes."""
        self._auto_import_views()
        return [route for route in self.routes if route.view_type == ViewType.CLASS]

    def create_url_patterns(self, prefix: Optional[str] = None) -> list[Any]:
        """
        Create Django URL patterns from registered routes.
        Returns a list of path() objects that can be used in urlpatterns.
        """
        self._auto_import_views()  # Ensure views are imported before creating patterns

        patterns = []
        for route in self.routes:
            if _is_websocket_route(route.route_type) or route.route_type == RouteType.MCP:
                continue
            patterns.append(self.build_url_pattern(route))

        return patterns

    def create_websocket_url_patterns(self):
        """Create Channels URL patterns for all registered websocket consumers."""
        self._auto_import_views()
        return [
            self.build_websocket_url_pattern(route)
            for route in self.routes
            if _is_websocket_route(route.route_type)
        ]

    def _get_route_kwargs(self, route: BloomerpRoute) -> dict:
        args = dict(route.args) if route.args else {}
        if route.model:
            args["model"] = route.model
        if route.module:
            args["module"] = route.module
        return args

    def _build_view_callable(self, route: BloomerpRoute, args: dict) -> Callable:
        if route.view_type == ViewType.CLASS:
            view_callable = route.view.as_view(**args)
        else:
            view_callable = route.view

        return view_callable

    def build_url_pattern(self, route: BloomerpRoute) -> Any:
        """Build a Django URL pattern for an HTTP route."""
        from django.urls import path as django_path, re_path as django_re_path

        if _is_websocket_route(route.route_type):
            raise ValueError("Websocket routes must be built with build_websocket_url_pattern")
        if route.route_type == RouteType.MCP:
            raise ValueError("MCP-only routes do not have Django URL patterns")

        args = self._get_route_kwargs(route)
        view_callable = self._build_view_callable(route, args)
        path_func = django_re_path if route.re_path is not None else django_path
        route_pattern = route.re_path if route.re_path is not None else route.path.lstrip('/')

        if route.view_type == ViewType.CLASS:
            return path_func(
                route_pattern,
                view_callable,
                name=route.url_name,
            )

        return path_func(
            route_pattern,
            view_callable,
            name=route.url_name,
            kwargs=args,
        )

    def build_websocket_url_pattern(self, route: BloomerpRoute):
        """Build a Channels URL pattern for a registered websocket consumer."""
        from django.urls import path as django_path, re_path as django_re_path

        if not _is_websocket_route(route.route_type):
            raise ValueError("Expected a websocket route")

        path_func = django_re_path if route.re_path is not None else django_path
        route_pattern = route.re_path if route.re_path is not None else route.path.lstrip('/')
        return path_func(route_pattern, route.view.as_asgi(), name=route.url_name)

    def clear_routes(self):
        """Clear all registered routes."""
        self.routes.clear()

    def filter(
        self,
        route_type: Optional[Literal['app', 'model', 'module', 'detail', 'api', 'api_model', 'api_detail', 'websocket', 'mcp']] | Optional[RouteType] = None,
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
            (e.g. 'app', 'module', 'model', 'detail', 'api'). If provided only routes
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
                route_names = f"{route.name or ''} {route.localized_name}"
                if name_query not in route_names.lower():
                    continue

            if description_query:
                route_descriptions = (
                    f"{route.description or ''} {route.localized_description}"
                )
                if description_query not in route_descriptions.lower():
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
        "channels",
    ]
)
