from django.conf import settings
from django.http import HttpRequest

def debug_mode(request: HttpRequest) -> dict:
    """
    Context processor to make DEBUG setting available in all templates.
    Usage in templates: {% if DEBUG %}...{% endif %}
    """
    return {
        'DEBUG': settings.DEBUG
    }
