import json

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404

from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.router import router
from bloomerp.services.sectioned_layout_services import normalize_layout_payload

# TODO: This should be an actual api endpoint instead of a component

@router.register(
    path="components/workspaces/save_workspace_layout/",
    name="components_workspaces_save_workspace_layout",
)
def save_workspace_layout(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON body", status=400)

    workspace_id = payload.get("workspace_id")
    if not workspace_id:
        return HttpResponse("Missing workspace_id", status=400)

    workspace = get_object_or_404(Workspace, pk=workspace_id)
    if workspace.user_id != request.user.id:
        return HttpResponse("Permission denied", status=403)

    layout = normalize_layout_payload(payload.get("layout"))
    valid_ids = {str(tile_id) for tile_id in Tile.objects.values_list("id", flat=True)}
    requested_ids = {
        str(item.id)
        for row in layout.rows
        for item in row.items
    }
    if not requested_ids.issubset(valid_ids):
        return HttpResponse("Unknown tile id in layout", status=400)

    workspace.layout = layout.model_dump()
    workspace.save(update_fields=["layout"])

    return JsonResponse({"status": "ok", "layout": layout.model_dump()})
