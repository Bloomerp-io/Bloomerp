from django.contrib.auth.decorators import login_required
from django.db.models import ObjectDoesNotExist
from django.http import Http404, HttpRequest, JsonResponse
from django.http import HttpResponse
from bloomerp.filters.definition import FilterField
from bloomerp.filters.utils import application_fields_to_filter_field_groups
from bloomerp.lookups.registry import LOOKUP_REGISTRY
from bloomerp.workspaces.utils import has_access_to_workspace
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.utils.models import get_model_and_content_type_or_404

    
    

@router.register(
    path="components/filters/fields",
    url_name="components_filters_fields"
)
@login_required
def fields(request: HttpRequest) -> HttpResponse:
    """Returns the filterable fields for a particular workspace or content type ID

    Args:
        request (HttpRequest): 

    Get Args:
        scope
        identifier
    
    Returns:
        HttpResponse: _description_
    """
    scope = request.GET.get("scope")
    identifier = request.GET.get("id")
    
    lookup_id = request.GET.get("lookup_id")
    field_path = request.GET.get("field_path")
    
    policy_manager = UserPolicyManager(request.user)
    
    if scope == "model":
        Model, content_type = get_model_and_content_type_or_404(identifier)
        
        if not policy_manager.has_global_permission(content_type):
            return HttpResponse("You don't have access to this", status_code=403)
        
        if field_path and lookup_id:
            fields = LOOKUP_REGISTRY.get_by_id(lookup_id).nested_fields_factory(
                Model,
                field_path
            )
            
            return JsonResponse(
                group.model_dump() for group in fields
            )
        
        application_fields = policy_manager.get_accessible_fields(content_type, BloomerpPermission.VIEW)
        
        return JsonResponse(
            application_fields_to_filter_field_groups(application_fields)    
        )
    
    if scope == "workspace":
        try:
            workspace = Workspace.objects.get(id=identifier)
        except ObjectDoesNotExist:
            return Http404("Workspace not found")
        
        if not has_access_to_workspace(workspace, request.user):
            return HttpResponse("You don't have access to this", status_code=403)
        
        fields = []
        
        for tile in workspace.get_tiles():
            filter_fields :list[str] = tile.get_tile_type_definition().filter_fields_factory(
                tile.get_config_object()
            )
            
            # Reconcile by type
            # Filters can appear to be the same if their field path and field type is the same

        
    return HttpResponse("Invalid scope", status_code=400)
            
        
        
        
        
        
    