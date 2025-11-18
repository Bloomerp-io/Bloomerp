from django.shortcuts import render
from registries.route_registry import router
from django.http import HttpResponse
from django.http import HttpRequest
from django.contrib.contenttypes.models import ContentType
from bloomerp.services.permission_services import get_queryset_for_user
from bloomerp.services.user_services import get_user_list_view_preference
from bloomerp.utils.filters import filter_model


@router.register(
    path="components/data_table_2/<int:content_type_id>/",
    name="components_data_table_2",
)
def data_table_2(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """
    Renders the data table component. A data table is a table that takes in a content type 
    id and renders a table of the corresponding model's data.
    It supports the following features:
    - filtering
    - permissions management
    - string searching
    """
    query = request.GET.get('q')
    
    # Get the content type
    try:
        content_type = ContentType.objects.get(id=content_type_id)
        Model = content_type.model_class()
    except ContentType.DoesNotExist:
        return HttpResponse("Content Type not found.", status=404)
    
    # Get the base queryset
    queryset = get_queryset_for_user(request.user, Model.objects.all())
    
    # Filter the queryset based on request parameters
    # TODO : Implement filtering logic using the legacy datatable.py as reference
    
    # Get fields for the user
    fields = get_user_list_view_preference(request.user, content_type)
    
    
    return render(request, 'components/objects/data_table.html', 
                  {
                      'content_type_id': content_type_id,
                      'queryset': queryset,
                      'fields': fields,
                  })