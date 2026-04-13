from django.conf import settings
from django.http import HttpRequest

def debug_mode(request: HttpRequest) -> dict:
    """
    Context processor to make DEBUG setting available in all templates.
    Usage in templates: {% if DEBUG %}...{% endif %}
    """
    return {
        'DEBUG': settings.DEBUG,
        'BLOOMERP_VITE_DEV_SERVER_URL': settings.BLOOMERP_SETTINGS.get('VITE_DEV_SERVER_URL', 'http://localhost:5173').rstrip('/'),
    }
    
def htmx_main_content_div(request: HttpRequest) -> dict:
    """
    Context processor to provide the HTMX main content div ID.
    Usage in templates: {{ HTMX_MAIN_CONTENT_DIV_ID }}
    """
    return {
        'HTMX_MAIN_CONTENT_DIV_ID': '#main-content'
    }
