import inspect
import os
import importlib.util
import inspect
from django.urls import path

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


class ComponentRouteFinder:
    '''Class used to find routes in a given directory. Used primarily for creating components.'''

    def __init__(
            self, 
            directory: str, 
            url_route_prefix: str = None,
            url_name_prefix: str = None
            ) -> None:
        '''Initialize the ComponentRouteFinder object.
        
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