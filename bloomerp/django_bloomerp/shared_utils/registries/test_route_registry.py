"""
Test file demonstrating the BloomerpRouteRegistry usage
with both function-based and class-based views.
"""

from django.http import HttpResponse
from django.views import View
from shared_utils.registries.route_registry import router


# Example 1: Function-based view with automatic path generation
@router.register(name="Home Page", description="Main landing page")
def home_view(request):
    """Main home page view."""
    return HttpResponse("Welcome to the home page!")


# Example 2: Function-based view with custom path
@router.register(path="/api/users/", route_type="list", name="User List API")
def user_list_view(request):
    """API endpoint to list all users."""
    return HttpResponse("User list API")


# Example 3: Class-based view with automatic path generation
@router.register(name="Contact Form", description="Contact us form")
class ContactView(View):
    """Contact form view."""
    
    def get(self, request):
        return HttpResponse("Contact form")
    
    def post(self, request):
        return HttpResponse("Form submitted")


# Example 4: Class-based view with custom path and model association
from django.contrib.auth.models import User

@router.register(path="/dashboard/profile/", models=User, route_type="detail")
class UserProfileView(View):
    """User profile dashboard view."""
    
    def get(self, request):
        return HttpResponse("User profile dashboard")


# Example 5: Function-based view with model association
@router.register(path="/admin/users/", models=User, route_type="list", name="Admin User Management")
def admin_user_list(request):
    """Admin interface for managing users."""
    return HttpResponse("Admin user management")


# Function to demonstrate registry capabilities
def print_registry_info():
    """Print information about all registered routes."""
    print("=== Route Registry Information ===")
    
    all_routes = router.get_routes()
    print(f"Total routes registered: {len(all_routes)}")
    
    print("\n--- All Routes ---")
    for route in all_routes:
        print(f"Path: {route.path}")
        print(f"Name: {route.name}")
        print(f"Type: {route.view_type}")
        print(f"Route Type: {route.route_type}")
        print(f"Models: {route.models}")
        print(f"Description: {route.description}")
        print("---")
    
    print("\n--- Function-based Views ---")
    fbv_routes = router.get_function_based_routes()
    for route in fbv_routes:
        print(f"FBV: {route.name} - {route.path}")
    
    print("\n--- Class-based Views ---")
    cbv_routes = router.get_class_based_routes()
    for route in cbv_routes:
        print(f"CBV: {route.name} - {route.path}")
    
    print("\n--- Routes by Type ---")
    for route_type in ['app', 'list', 'detail']:
        routes = router.get_routes_by_type(route_type)
        print(f"{route_type.title()} routes: {len(routes)}")


if __name__ == "__main__":
    print_registry_info()
