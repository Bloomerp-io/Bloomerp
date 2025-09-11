#!/usr/bin/env python3

import os
import sys
import django
from django.conf import settings

# Add the project to Python path
sys.path.append('/Users/davidbloomer/Workspace/Bloomerp/bloomerp/django_bloomerp')

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

print("Testing auto-discovery route registry...")

# Import the registry
from shared_utils.registries.route_registry import router

# Get routes - this should trigger auto-discovery
print("Getting routes...")
routes = router.get_routes()

print(f"Found {len(routes)} routes:")
for route in routes:
    print(f"  - Path: {route.path}")
    print(f"    Name: {route.name}")
    print(f"    View type: {route.view_type}")
    print(f"    Description: {route.description}")
    print()

if any(route.path == "/hey/" for route in routes):
    print("✅ Successfully found the /hey/ route from test.py!")
else:
    print("❌ Could not find the /hey/ route from test.py")
    print("Routes found:", [route.path for route in routes])
