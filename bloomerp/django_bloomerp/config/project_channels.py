"""Project-owned websocket routes. This file is never generated."""

try:
    from config.project_routing import websocket_urlpatterns
except ModuleNotFoundError as exc:
    if exc.name != "config.project_routing":
        raise
    websocket_urlpatterns = []
