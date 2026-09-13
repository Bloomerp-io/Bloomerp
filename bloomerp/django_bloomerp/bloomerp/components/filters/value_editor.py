from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest
from django.http import HttpResponse
from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.lookups.definition import LookupDefinition
from bloomerp.router import router

@router.register(
    path="components/filters/value_editor",
    url_name="components_filters_value_editor"
)
@login_required
def value_editor(request: HttpRequest) -> HttpResponse:
    """Returns the value editor for a filter

    Args:
        request (HttpRequest): The request object
    POST args:
        field_type
        lookup_id
        scope
        
    Returns:
        HttpResponse: the response
    """
    field_type = ...
    lookup_id = ...
    
    lookup : LookupDefinition = None
    for l in FIELD_TYPE_REGISTRY.get(field_type).lookups:
        if l.id == l:
            lookup = l
    
    if not lookup:
        return Http404("Lookup not found")
    
    field = lookup.default_form_factory(
        
    )
    
    return {
        "widget" : "",
        
    }
    