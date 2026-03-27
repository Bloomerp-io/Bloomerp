import json
from django.http import HttpResponse, HttpRequest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from bloomerp.models import BloomerpModel
from bloomerp.utils.models import string_search
from bloomerp.router import router

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
        # Check if the model has a string_search method, it is inherited from BloomerpModel
        if not hasattr(Model, 'string_search'):
            # Add the string_search method to the model
            Model.string_search = classmethod(string_search)
        
        results = Model.string_search(query)
    else:
        # Take first 10 objects
        results = Model.objects.all()[:10]
    
    # Construct response
    

    resp = {
        'objects' : [
            {
                'id': obj.pk,
                'string_representation': str(obj),
                'detail_url': _get_detail_url(obj),
            } for obj in results
        ]
    }

    return HttpResponse(
        json.dumps(resp),
        content_type="application/json"
    )

