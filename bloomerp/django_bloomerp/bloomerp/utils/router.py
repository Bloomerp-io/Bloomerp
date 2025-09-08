import os
import importlib.util
import inspect
from django.urls import path
from django.db.models import Model
from functools import wraps
from django.conf import settings
from bloomerp.utils.models import model_name_plural_slug, model_name_plural_underline, get_base_model_route
from bloomerp.models import Link
from typing import List, Callable
import re
import traceback

# Helper functions
def _get_name_or_slug(obj, slug=False):
    """
    Returns the name of the class or function.
    
    :param obj: The class or function object.
    :param slug: Boolean, if True returns a slugified version of the name.
    :return: A string, either a capitalized name or slugified name.
    """
    # Get the name of the function or class
    name = obj.__name__

    # Convert camelCase or snake_case to a human-readable format
    if slug:
        # If slug is True, return a slugified version of the name
        if re.match(r'^[a-zA-Z0-9_]+$', name):  # Handles snake_case (functions)
            return name.replace('_', '-').lower()
        else:  # Handles CamelCase (classes)
            return re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()
    else:
        # If slug is False, return a human-readable capitalized name
        if re.match(r'^[a-zA-Z0-9_]+$', name):  # Handles snake_case (functions)
            return name.replace('_', ' ').title()
        else:  # Handles CamelCase (classes)
            return re.sub(r'(?<!^)(?=[A-Z])', ' ', name).title()
        
def _clean_appended_url(appended_url:str) -> str:
    """
    Helper function to clean the appended URL for a route.
    """
    if not appended_url:
        return ''

    if appended_url.startswith('/'):
        appended_url = appended_url[1:]    

    if appended_url.endswith('/'):
        appended_url = appended_url[:-1]
    return appended_url

def _underline(string:str) -> str:
    """
    Helper function to convert a string to an underline-separated string.
    """
    return string.replace(' ', '_').lower()

def _create_absoulte_path_for_model(model: Model, route_type: str, appended_url: str) -> str:
    """
    Helper function to create an absolute path for a route based on the model, route type, and name.
    """
    appended_url = _clean_appended_url(appended_url)

    if route_type not in ['list', 'detail']:
        raise ValueError("Invalid route type. Must be 'list' or 'detail'.")
    
    if not model:
        raise ValueError("A model must be provided for list and detail routes.")

    if route_type == 'list':
        if appended_url == '':
            return model_name_plural_slug(model) + '/'
        p = model_name_plural_slug(model) + '/' + appended_url + '/'
    elif route_type == 'detail':
        if appended_url == '':
            return model_name_plural_slug(model) + '/<int_or_uuid:pk>/'
        p = model_name_plural_slug(model) + '/<int_or_uuid:pk>/' + appended_url + '/'
    return p


def _create_relative_path(model:Model, route_type:str, name:str):
    """
    Create a relative path for a route based on the model, route type, and name.
    """
    if route_type == 'list':
        return model_name_plural_underline(model) + '_' + _underline(name)
    elif route_type == 'detail':
        return model_name_plural_underline(model) + '_detail_' + _underline(name)
    else:
        return _underline(name)

# Route decorator
def route(path=None):
    def decorator(func):
        if path is None:
            # Build default path using function name and parameters
            sig = inspect.signature(func)
            parts = [func.__name__]

            for name, param in sig.parameters.items():
                if name == 'request':
                    continue  # Skip 'request' parameter
                param_type = 'str'  # Default type
                if param.annotation == int:
                    param_type = 'int'
                elif param.annotation == str:
                    param_type = 'str'
                # Add other types as needed
                parts.append(f'<{param_type}:{name}>')
            func.route = '/' + '/'.join(parts) + '/'

        else:
            func.route = path
        return func
    return decorator

class RouteFinder:
    '''Class used to find routes in a given directory. Used primarily for creating components.'''

    def __init__(
            self, 
            directory: str, 
            url_route_prefix: str = None,
            url_name_prefix: str = None
            ) -> None:
        '''Initialize the RouteFinder object.
        
        Args:
            directory (str): The directory to search for routes.
            prefix (str): The prefix to add to the url routes.
            url_name_prefix (str): The prefix to add to the url names.
        '''
        self.directory = directory
        self.urlpatterns = []
        self.prefix = url_route_prefix
        if not url_name_prefix:
            self.url_name_prefix = ''
        else:
            self.url_name_prefix = url_name_prefix + '_'


    def find_python_files(self):
        """Find all Python files in the specified directory."""
        py_files = []
        for root, _, files in os.walk(self.directory):
            for file in files:
                if file.endswith(".py") and file != os.path.basename(__file__):
                    py_files.append(os.path.join(root, file))
        return py_files

    def load_module(self, filepath):
        """Load a module from a given file path."""
        module_name = os.path.splitext(os.path.basename(filepath))[0]
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def find_routes_in_module(self, module):
        """Look for functions with a 'route' attribute in a module."""
        for name, obj in inspect.getmembers(module):
            if inspect.isfunction(obj) and hasattr(obj, 'route'):
                self.urlpatterns.append(path(self.prefix + obj.route, obj, name=self.url_name_prefix + obj.__name__))

    def generate_urlpatterns(self):
        """Scan the directory, find routes, and populate urlpatterns."""
        py_files = self.find_python_files()
        for py_file in py_files:
            try:
                module = self.load_module(py_file)
                self.find_routes_in_module(module)
            except Exception as e:
                print(f"Error loading module {py_file}: {e}")
        return self.urlpatterns

class BloomerpRoute:
    '''
    Class used to store information about a route in the router.
    Not used on its own, but as a part of the BloomerpRouter class.
    '''

    def __init__(self, 
                model: Model, 
                route_type: str, 
                path: str,
                relative_path: str,
                view: callable, 
                route_name: str,
                description: str = None,
                override: bool = False,
                view_type = 'function',
                args : dict = None
                ) -> None:
        self.model = model
        self.route_type = route_type
        self.path = path
        self.view = view
        self.route_name = route_name
        self.description = description
        self.override = override
        self.relative_path = relative_path
        self.view_type = view_type
        self.args = args

    def generate_link(self) -> None:
        """
        Generate a Link object for the route.
        """
        from django.contrib.contenttypes.models import ContentType
        if self.model:
            # Get content type for the model
            content_type = ContentType.objects.get_for_model(self.model)
        else:
            content_type = None

        if self.route_type == 'app':
            level = 'APP'
        elif self.route_type == 'list':
            level = 'LIST'
        elif self.route_type == 'detail':
            level = 'DETAIL'

        try:
            Link.objects.update_or_create(
                url = self.relative_path,
                is_absolute_url = False,
                content_type=content_type,
                level = level,
                defaults={
                    'description': self.description,
                    'name': self.route_name,
                    'url' : self.relative_path,
                }
            )
            # Delete any existing links with the same URL
            Link.objects.filter(url=self.relative_path).exclude(name=self.route_name).delete()

        except Exception as e:
            # Delete any existing links with the same URL
            Link.objects.filter(url=self.relative_path).first().delete()

    def create_urlpattern(self):
        """
        Create a URL pattern for the route.
        """
        if not self.args:
            self.args = {}

        if self.view_type == 'function':
            return path(self.path, self.view, name=self.relative_path)
        
        elif self.view_type == 'class':
            if self.route_type in ['list', 'detail']:
                return path(self.path, self.view.as_view(model = self.model, **self.args), name=self.relative_path)
            else:
                return path(self.path, self.view.as_view(**self.args), name=self.relative_path)
        
    def set_view(self, view: Callable):
        """
        Set the view for the route.
        """
        self.view = view

class BloomerpRouter:
    def __init__(self):
        # Instance-level list to store routes
        self.routes : List[BloomerpRoute] = []

    def bloomerp_route(
            self, 
            path : str = None,
            models : List[Model] | Model = None,
            exclude_models : List[Model] = None,
            route_type='list', 
            name : str = None,   
            override : bool = False,
            description : str = None,
            url_name : str = None,
            from_func : Callable = None,
            args : dict = None
            ):
        """
        Decorator for registering routes for a model.
        Works for both function-based and class-based views.

        Implementation:
        - Validates the provided parameters.
        - Handles different cases for models (single, list, all).
        - Creates relative and absolute paths for the routes.
        - Appends route information to the router's list.
        - Supports both function-based views (FBVs) and class-based views (CBVs).

        Args:
            path: The path for the route.
            models: The model for which the route is being registered. If no model is given, it is an ap   evel route.
            exclude_models: A list of models to exclude from the route. Only works when models is '__all__'.
            route_type: The type of route. Can be 'list', 'detail', or 'app'. Ap   evel routes don't require a model.
            name: The name of the route. Will be used to generate the Link object for the route.
            override: If True, the route will override any existing route with the same path.
            description: A description of the route. Will be used to generate the Link object for the route.
            url_name: The URL name for the route.
            from_func: A function that takes all models as input, and returns a dictionary with parameters or False
            args: Additional args to be passed to the view
        """
        def decorator(view):
            from django.contrib.contenttypes.models import ContentType
            from bloomerp.models import Widget
            from django.apps import apps
            nonlocal path, models, route_type, name, description, override, exclude_models, url_name, from_func, self, args

            # Set temp_routes
            temp_routes = []
            
            # ---------------------
            # VALIDATION
            # ---------------------
            if not from_func:
                if exclude_models:
                    models = '__all__'

                if not models and route_type != 'app':
                    raise ValueError("A model must be provided for list and detail routes.")
                
                if models and route_type == 'app':
                    raise ValueError("You can't provide a model for an app route.")

                if route_type not in ['list', 'detail', 'app']:
                    raise ValueError("Invalid route type. Must be 'list', 'detail', or 'app'.")
                
                if models and exclude_models:
                    if models != '__all__':
                        raise ValueError("You can't provide both models and exclude_models.")

                if not exclude_models:
                    exclude_models = []

                if description is None:
                    description = view.__doc__
                
                if not name:
                    name = _get_name_or_slug(view, slug=False)

            # Models will be given in the case of LIST and DETAIL routes
            if from_func:
                models = apps.get_models()
                for model in models:
                    params : dict | list[dict] | bool  = from_func(model)

                    if params == False:
                        continue
                    
                    # Multiple params given
                    if type(params) == list:
                        for param_dict in params:
                            
                            route = BloomerpRoute(
                                model=param_dict['model'],
                                route_type=param_dict['route_type'],
                                path=_create_absoulte_path_for_model(param_dict['model'], param_dict['route_type'], param_dict['path']),
                                view = None, # This will be set later
                                route_name=param_dict['name'],
                                description=param_dict['description'],
                                override=False,
                                relative_path=_create_relative_path(param_dict['model'], param_dict['route_type'],param_dict['url_name']),
                                args=param_dict['args']
                            )
                            temp_routes.append(route)

                    # Single dictionary given
                    else:
                        route = BloomerpRoute(
                                model=param_dict['models'],
                                route_type=param_dict['route_type'],
                                path=param_dict['path'],
                                view = None, # This will be set later
                                route_name=param_dict['name'],
                                description=param_dict['description'],
                                override=False,
                                relative_path=param_dict['url_name'],
                                args=args
                            )
                        
                        temp_routes.append(route)

            elif models == '__all__':
                ContentTypes = ContentType.objects.all()
                for ContentType in ContentTypes:
                    model = ContentType.model_class()
                    model_name = model._meta.verbose_name.title()

                    # Check if the model is in the exclude list
                    if model in exclude_models:
                        continue
                    
                    # Create the relative path for the model
                    if not url_name:
                        relative_path = _create_relative_path(model, route_type, name)
                    else:
                        relative_path = _create_relative_path(model, route_type, url_name)

                    # Create the absolute path for the model
                    p = _create_absoulte_path_for_model(model, route_type, path)
                    
                    # Update description and name for the model
                    try:
                        route_name = name.format(model=model_name)
                    except:
                        route_name = name + ' ' + model_name
                    

                    try:
                        desc = description.format(model=model_name)
                    except:
                        desc = description + ' ' + model_name

                    # Append the route information to the router's list
                    route = BloomerpRoute(
                        model=model,
                        route_type=route_type,
                        path=p,
                        view = None, # This will be set later
                        route_name=route_name,
                        description=desc,
                        override=override,
                        relative_path=relative_path,
                        args=args
                    )
                    temp_routes.append(route)
            elif type(models) == list:
                for model in models:
                    model_name = model._meta.verbose_name.title()

                    # Create the relative path for the model
                    if not url_name:
                        relative_path = _create_relative_path(model, route_type, name)
                    else:
                        relative_path = _create_relative_path(model, route_type, url_name)
                    
                    try:
                        route_name = name.format(model=model_name)
                    except:
                        route_name = name + ' ' + model_name
                    

                    try:
                        desc = description.format(model=model_name)
                    except:
                        desc = description + ' ' + model_name

                    created_path = _create_absoulte_path_for_model(model, route_type, path)
                    # Append the route information to the router's list
                    route = BloomerpRoute(
                        model=model,
                        route_type=route_type,
                        path=created_path,
                        view = None, # This will be set later
                        route_name=route_name,
                        description=desc,
                        override=override,
                        relative_path=relative_path,
                        args=args
                    )
                    temp_routes.append(route)
            elif models:
                # Single model case
                model_name = models._meta.verbose_name.title()

                # Create the relative path for the model
                if not url_name:
                    relative_path = _create_relative_path(models, route_type, name)
                else:
                    relative_path = _create_relative_path(models, route_type, url_name)

                created_path = _create_absoulte_path_for_model(models, route_type, path)

                try:
                    route_name = name.format(model=model_name)
                except:
                    route_name = name + ' ' + model_name
                

                try:
                    desc = description.format(model=model_name)
                except:
                    desc = description + ' ' + model_name

                # Append the route information to the router's list
                route = BloomerpRoute(
                    model=models,
                    route_type=route_type,
                    path=created_path,
                    view = None, # This will be set later
                    route_name=route_name,
                    description=desc,
                    override=override,
                    relative_path=relative_path,
                    args=args
                ) 
                temp_routes.append(route)
            elif models == None:
                # App-level route case
                if not url_name:
                    relative_path = _create_relative_path(None, route_type, name)
                else:
                    relative_path = url_name

                if not path.endswith('/') and path != '':
                    path = path + '/'

                # Append the route information to the router's list
                route = BloomerpRoute(
                    model=None,
                    route_type=route_type,
                    path=path,
                    view = None, # This will be set later
                    route_name=name,
                    description=description,
                    override=override,
                    relative_path=relative_path,
                    args=args
                )
                temp_routes.append(route)

            # For function-based views (FBVs)
            if callable(view) and not hasattr(view, 'as_view'):
                @wraps(view)
                def wrapped_view(*args, **kwargs):
                    return view(*args, **kwargs)

                # Append the route information to the router's list
                for route in temp_routes:
                    route.view = wrapped_view
                    route.view_type = 'function'
                    self.routes.append(route)

                return wrapped_view

            # For class-based views (CBVs)
            elif hasattr(view, 'as_view'):
                # Use the `as_view()` method to create a callable view

                # Append the route information to the router's list
                for route in temp_routes:
                    route.view = view
                    route.view_type = 'class'
                    self.routes.append(route)
                
                # Return the original view class, not the callable, for further decoration if needed
                return view

            else:
                raise TypeError("The provided view is neither a valid function-based view nor a class-based view.")

        return decorator

    
    def get_routes_for_model(self, model) -> List[BloomerpRoute]:
        """
        Get all routes registered for a specific model.
        """
        return [route for route in self.routes if (route.model == model or route.model == '__all__')]

    def get_detail_view_routes_for_model(self, model) -> List[BloomerpRoute]:
        """
        Get all detail view routes registered for a specific model.
        """
        routes = []
        for route in self.routes:
            route : BloomerpRoute
            if (route.model == model or route.model=='__all__') and route.route_type == 'detail':
                routes.append(route)

        return routes
    
    def get_list_view_routes_for_model(self, model):
        """
        Get all list view routes registered for a specific model.
        """
        routes = []
        for route in self.routes:
            route : BloomerpRoute
            if route.model == model and route.route_type == 'list':
                routes.append(route)
        return routes

    def get_app_routes(self) -> List[BloomerpRoute]:
        """
        Get all app-level routes registered in the router.
        """
        return [route for route in self.routes if route.route_type == 'app']

    def _create_relative_path(self, model, route_type, name):
        """
        Create a relative path for a route based on the model, route type, and name.
        """
        if route_type == 'list':
            return model_name_plural_underline(model) + '_' + _underline(name)
        elif route_type == 'detail':
            return model_name_plural_underline(model) + '_detail_' + _underline(name)
        else:
            return _underline(name)
    
class BloomerpRouterHandler:
    '''
    A class to handle multiple routers in a single place.
    Makes it easier to query and work with multiple routers.
    '''
    def __init__(self, routers: List[BloomerpRouter]):
        self.routers = routers

    def get_detail_view_routes_for_model(self, model: Model) -> List[BloomerpRoute]:
        """
        Generate detail view routes for a specific model from all routers.
        """
        routes = []
        for router in self.routers:
            routes.extend(router.get_detail_view_routes_for_model(model))
        return routes
    
    def get_list_view_routes_for_model(self, model: Model) -> List[BloomerpRoute]:
        """
        Generate list view routes for a specific model from all routers.
        """
        routes = []
        for router in self.routers:
            routes.extend(router.get_list_view_routes_for_model(model))
        return routes
    
    def get_routes_for_model(self, model: Model) -> List[BloomerpRoute]:
        """
        Generate all routes for a specific model from all routers.
        """
        routes = []
        for router in self.routers:
            routes.extend(router.get_routes_for_model(model))
        return routes
    
    def get_app_routes(self) -> List[BloomerpRoute]:
        """
        Generate all app-level routes from all routers.
        """
        routes = []
        for router in self.routers:
            routes.extend(router.get_app_routes())
        return routes

    def generate_links(self) -> None:
        """
        Generate Link objects for all routes in all routers.
        """
        for router in self.routers:
            for route in router.routes:
                route.generate_link()

    def is_overriden(self, path: str) -> bool:
        """
        Check if a route with the given path is overriden in any of the routers.
        """
        for router in self.routers:
            for route in router.routes:
                if route.path == path:
                    return True
        return False

    def overriden_paths(self) -> List[str]:
        """
        Get a list of overriden routes from all routers.
        """
        routes = []
        for router in self.routers:
            for route in router.routes:
                if route.override:
                    routes.append(route.path)
        return routes

from importlib import import_module
def _get_routers_from_settings() -> List[BloomerpRouter]:
    """
    Helper function to get the router objects based on the ones given in the settings.
    """
    routers = []

    # Get the routers from the settings
    try:
        router_paths = settings.BLOOMERP_SETTINGS['ROUTERS']
    except:
        print("No routers found in the settings.")
        router_paths = []
    
    for router_path in router_paths:
        try:
            # Dynamically import the module containing the router
            module_path, router_name = router_path.rsplit(".", 1)
            module = import_module(module_path)
            
            # Get the router class from the module
            router = getattr(module, router_name)
            
            # Add the router to the routers list
            routers.append(router)
        except (ImportError, AttributeError, TypeError) as e:
            print(f"Error importing {router_path}: {e}")
            traceback.print_exc()
    return routers

