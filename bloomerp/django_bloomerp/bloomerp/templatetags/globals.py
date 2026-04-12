from django.conf import settings
from django import template

register = template.Library()

@register.simple_tag
def globals(name:str):
    '''
    Returns a global variable from the BLOOMERP_SETTINGS configuration in settings.py.

    Usage:
    {% load globals %}
    {% globals "variable_name" %}

    '''
    if not hasattr(settings, "BLOOMERP_SETTINGS"):
        raise ValueError("BLOOMERP_SETTINGS not found in settings.py. Please configure it according to the documentation.")
    
    globals:dict = settings.BLOOMERP_SETTINGS.get("globals")
    value = globals.get(name)
    return value

