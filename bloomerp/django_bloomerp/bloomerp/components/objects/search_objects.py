import json

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.urls import NoReverseMatch, reverse

from bloomerp.models import BloomerpModel
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.object_services import string_search_on_queryset


def _get_detail_url(obj: Model) -> str:
    """Return the object's detail URL when its model exposes one."""
    try:
        return obj.get_absolute_url()
    except (AttributeError, NoReverseMatch):
        try:
            from bloomerp.utils.models import get_detail_view_url
            return reverse(get_detail_view_url(obj.__class__), kwargs={"pk": obj.pk})
        except (AttributeError, NoReverseMatch):
            return ""


@router.register(
    path="components/search-objects/<int:content_type_id>/",
    name="components_search_objects",
)
def search_objects(request:HttpRequest, content_type_id:int) -> HttpResponse:
    """Return searchable or exact-ID objects visible to the current user."""
    Model : BloomerpModel = ContentType.objects.get_for_id(content_type_id).model_class()
    query = request.GET.get('fk_search_results_query')
    selected_ids = request.GET.getlist('fk_selected_id')[:100]
    permission_manager = UserPolicyManager(request.user)
    
    # Get the base queryset
    base_queryset = permission_manager.get_queryset(
        Model,
        BloomerpPermission.VIEW
    )
    
    if selected_ids:
        primary_key_field = Model._meta.pk
        valid_ids = []
        for selected_id in selected_ids:
            try:
                valid_ids.append(primary_key_field.to_python(selected_id))
            except (TypeError, ValueError, ValidationError, OverflowError):
                continue
        results = base_queryset.filter(pk__in=valid_ids)
    elif query:
        results = string_search_on_queryset(
            queryset=base_queryset, 
            query=query
        )
    else:
        # Take first 10 objects
        results = base_queryset[:10]
    
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
