from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from bloomerp.router import router
from bloomerp.services.workspace_services import UserWorkspaceService


@router.register(
    path="components/workspaces/available_workspace_tiles/",
    name="components_workspaces_available_workspace_tiles",
)
def available_workspace_tiles(request: HttpRequest) -> HttpResponse:
    if not request.user.is_authenticated:
        return HttpResponse("Permission denied", status=403)
    
    service = UserWorkspaceService(request.user)
    tiles = service.get_available_workspace_tiles()

    return render(
        request,
        "components/layouts/available_items.html",
        {"items": tiles},
    )
