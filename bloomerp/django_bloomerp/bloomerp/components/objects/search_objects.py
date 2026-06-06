import json
from django.http import HttpResponse, HttpRequest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from bloomerp.models import BloomerpModel
from bloomerp.router import router
from bloomerp.services.object_services import string_search_on_queryset

def _get_detail_url(obj) -> str:
    """Helper function to get the detail url"""
    try:
        return obj.get_absolute_url()
    except Exception:
        try:
            from bloomerp.utils.models import get_detail_view_url
            return reverse(get_detail_view_url(obj.__class__), kwargs={"pk": obj.pk})
        except Exception:
            return ""


@router.register(
    path="components/search-objects/<int:content_type_id>/",
    name="components_search_objects",
)
def search_objects(request:HttpRequest, content_type_id:int) -> HttpResponse:
    """Component that returns search results for a given query

    Args:
        request (HttpRequest): request object
        content_type_id (int): content type id

    Returns:
        HttpResponse: the response
    """
    Model : BloomerpModel = ContentType.objects.get_for_id(content_type_id).model_class()
    query = request.GET.get('fk_search_results_query')

    if query:
        results = string_search_on_queryset(Model.objects.all(), query)
    else:
        # Take first 10 objects
        results = Model.objects.all()[:10]
    
    # Construct response
    

    resp = {
        'objects' : [
            {
                'id': str(obj.pk),
                'string_representation': str(obj),
                'detail_url': _get_detail_url(obj),
            } for obj in results
        ]
    }

    return HttpResponse(
        json.dumps(resp),
        content_type="application/json"
    )
