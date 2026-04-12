from bloomerp.models.workspaces.tile import Tile
from bloomerp.router import router
from bloomerp.services.workspace_services import render_tile_to_string
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@router.register(
    path="components/render_workspace_tile/",
    name="components_render_workspace_tile",
)
def render_workspace_tile(request: HttpRequest) -> HttpResponse:
    """Renders a workspace tile

    Args:
        request (HttpRequest): the workspace tile

    Returns:
        HttpResponse: _description_
    """

    tile_id = request.GET.get("tile_id")
    if not tile_id:
        return HttpResponse(status=404)

    tile = Tile.objects.get(id=tile_id)
    try:
        colspan = max(1, int(request.GET.get("colspan", 1)))
    except (TypeError, ValueError):
        colspan = 1
    try:
        max_cols = max(1, int(request.GET.get("max_cols", 4)))
    except (TypeError, ValueError):
        max_cols = 4

    error = False
    try:
        content = render_tile_to_string(
            tile,
            request.user
        )
    except Exception as e:
        content = e
        error = True

    context = {
        "icon" : tile.icon,
        "title" : tile.name,
        "description" : tile.description,
        "content" : content,
        "tile_id" : tile.id,
        "colspan" : colspan,
        "max_cols" : max_cols,
        "tile_type": tile.type.lower(),
    }

    return render(request, "components/workspaces/render_workspace_tile.html", context=context)
