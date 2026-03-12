from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from bloomerp.router import router
from bloomerp.services.sectioned_layout_services import get_available_workspace_tiles


@router.register(
    path="components/workspaces/available_workspace_tiles/",
    name="components_workspaces_available_workspace_tiles",
)
def available_workspace_tiles(request: HttpRequest) -> HttpResponse:
    if not request.user.is_authenticated:
        return HttpResponse("Permission denied", status=403)

    return render(
        request,
        "components/layouts/available_items.html",
        {"items": get_available_workspace_tiles()},
    )
