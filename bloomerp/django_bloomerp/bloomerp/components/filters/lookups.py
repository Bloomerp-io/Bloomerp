from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.http import HttpResponse
from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.router import router

@router.register(
    path="components/filters/lookups",
    url_name="components_filters_lookups"
)
@login_required
def lookups(request: HttpRequest) -> HttpResponse:
    """Returns a list of available lookups

    Args:
        request (HttpRequest): the request object
        
    GET Args:
        field_type
        
    Returns:
        HttpResponse: a list of available lookups
    """
    field_type = FIELD_TYPE_REGISTRY.get(
        request.GET.get("field_type")
    )
    
    return JsonResponse(
        [
            {
                "id" : lookup.id,
                "label" : lookup.label,
                "nested" : lookup.nested,
            }
            for lookup in field_type.lookups
        ]
    )
    