import json
from django.http import HttpResponse, HttpRequest
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import BloomerpModel
from bloomerp.utils.models import string_search
from registries.route_registry import router


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
                'string_representation': str(obj)
            } for obj in results
        ]
    }

    return HttpResponse(
        json.dumps(resp),
        content_type="application/json"
    )