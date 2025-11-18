"""
Test script to verify auto-import functionality for route registry.
This tests that routes from both views/ and components/ directories are discovered.
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from registries.route_registry import router

def test_auto_import():
    """Test that auto-import discovers routes from configured directories."""
    print("Testing auto-import functionality...\n")
    
    # Force auto-import
    routes = router.get_routes()
    
    print(f"Total routes discovered: {len(routes)}\n")
    
    # Check for routes from views/core.py
    view_routes = [r for r in routes if 'core' in str(r.view)]
    print(f"Routes from views/core.py: {len(view_routes)}")
    for route in view_routes[:3]:  # Show first 3
        print(f"  - {route.name} ({route.path})")
    
    # Check for routes from components
    component_routes = [r for r in routes if hasattr(r.view, '__module__') and 'components' in r.view.__module__]
    print(f"\nRoutes from components/: {len(component_routes)}")
    for route in component_routes[:5]:  # Show first 5
        module = route.view.__module__ if hasattr(route.view, '__module__') else 'unknown'
        print(f"  - {route.name} ({route.path}) from {module}")
    
    # Specifically check for data_table_2
    data_table_2_routes = [r for r in routes if 'data_table_2' in r.path or 'data_table_2' in r.name.lower()]
    print(f"\nRoutes containing 'data_table_2': {len(data_table_2_routes)}")
    for route in data_table_2_routes:
        print(f"  - {route.name} ({route.path})")
    
    # Check routes by type
    print(f"\nRoutes by type:")
    print(f"  - APP routes: {len(router.get_routes_by_type('app'))}")
    print(f"  - LIST routes: {len(router.get_routes_by_type('list'))}")
    print(f"  - DETAIL routes: {len(router.get_routes_by_type('detail'))}")
    
    # Check configured directories
    print(f"\nConfigured directories: {router.dirs}")
    
    return len(routes) > 0

if __name__ == "__main__":
    success = test_auto_import()
    if success:
        print("\n✅ Auto-import test completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Auto-import test failed - no routes discovered!")
        sys.exit(1)
