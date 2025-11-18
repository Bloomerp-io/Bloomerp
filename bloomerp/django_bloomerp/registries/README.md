# BloomerpRouteRegistry

A flexible route registry system for Django that allows you to register both function-based views (FBVs) and class-based views (CBVs) using decorators.

## Features

- **Universal Decorator**: Works with both function-based and class-based views
- **Automatic Path Generation**: Generates URL paths automatically based on view names
- **Model Association**: Associate routes with Django models
- **Route Types**: Support for different route types (`app`, `list`, `detail`)
- **URL Pattern Generation**: Generate Django URL patterns from registered routes
- **Query Methods**: Find routes by model, type, or view type

## Basic Usage

### Function-Based Views

```python
from shared_utils.registries.route_registry import router
from django.http import HttpResponse

# Simple registration with auto-generated path
@router.register()
def home_view(request):
    """Main home page."""
    return HttpResponse("Home Page")

# Custom path and parameters
@router.register(path="/api/users/", route_type="list", name="User API")
def user_list_api(request):
    """API to list users."""
    return HttpResponse("User List API")
```

### Class-Based Views

```python
from django.views import View
from shared_utils.registries.route_registry import router

# Simple registration
@router.register(name="Contact Form")
class ContactView(View):
    """Contact form view."""
    
    def get(self, request):
        return HttpResponse("Contact Form")
    
    def post(self, request):
        return HttpResponse("Form Submitted")

# With model association
from django.contrib.auth.models import User

@router.register(path="/profile/", models=User, route_type="detail")
class UserProfileView(View):
    """User profile view."""
    
    def get(self, request):
        return HttpResponse("User Profile")
```

## Decorator Parameters

- **path** (str, optional): Custom URL path. Auto-generated if not provided.
- **models** (Model/List[Model]/str, optional): Associate route with Django model(s).
- **route_type** (str, default='app'): Type of route (`'app'`, `'list'`, `'detail'`).
- **name** (str, optional): Display name for the route. Auto-generated if not provided.
- **description** (str, optional): Route description. Uses view docstring if not provided.
- **override** (bool, default=False): Whether to override existing routes with same path.

## Registry Methods

### Getting Routes

```python
# Get all routes
all_routes = router.get_routes()

# Get routes by model
user_routes = router.get_routes_by_model(User)

# Get routes by type
list_routes = router.get_routes_by_type('list')

# Get function-based view routes
fbv_routes = router.get_function_based_routes()

# Get class-based view routes
cbv_routes = router.get_class_based_routes()
```

### Generating URL Patterns

```python
# Generate Django URL patterns
urlpatterns = router.create_url_patterns()

# Use in your urls.py
from django.urls import include
from shared_utils.registries.route_registry import router

urlpatterns = [
    # Your other patterns
] + router.create_url_patterns()
```

## Route Information

Each registered route contains:

- `path`: The URL path
- `models`: Associated Django model(s)
- `route_type`: Type of route (`app`, `list`, `detail`)
- `name`: Display name
- `view`: The view function or class
- `view_type`: Either `'function'` or `'class'`
- `description`: Route description
- `override`: Whether it overrides existing routes

## Advanced Usage

### Model Association Examples

```python
from myapp.models import Product, Category

# Single model
@router.register(models=Product, route_type="detail")
def product_detail(request, pk):
    return HttpResponse(f"Product {pk}")

# Multiple models
@router.register(models=[Product, Category], route_type="list")
def catalog_view(request):
    return HttpResponse("Product Catalog")
```

### Route Types

- **app**: Application-level routes (default)
- **list**: Routes for listing objects (typically associated with models)
- **detail**: Routes for individual object details (typically associated with models)

### Integration with Existing Router

The route registry is designed to work alongside the existing `BloomerpRouter` system. You can use both systems in the same project:

```python
# Using the existing BloomerpRouter
from shared_utils.router.view_router import BloomerpRouter
existing_router = BloomerpRouter()

# Using the new RouteRegistry
from shared_utils.registries.route_registry import router as route_registry

# Both can coexist and serve different purposes
```

## Best Practices

1. **Use descriptive names**: Provide clear names for your routes
2. **Document your views**: Use docstrings - they become route descriptions
3. **Consistent path patterns**: Follow a consistent URL structure
4. **Model association**: Associate routes with models when appropriate
5. **Route types**: Use appropriate route types for better organization

## Examples

See `test_route_registry.py` for complete working examples of both function-based and class-based view registration.
