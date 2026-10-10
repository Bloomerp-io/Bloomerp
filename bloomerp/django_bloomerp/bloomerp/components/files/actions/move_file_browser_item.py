"""Move physical file nodes without changing their object references."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from bloomerp.files.access import FileAccessManager
from bloomerp.router import router


@router.register(
    path="components/files/items/move/", name="components_files_move_browser_item"
)
@login_required
def move_file_browser_item(request: HttpRequest) -> HttpResponse:
    """Move a physical file or folder after checking source and destination access."""
    from bloomerp.models.files.file_node import FileNode

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)
    item_type = request.POST.get("item_type")
    if item_type not in {"file", "folder"}:
        return HttpResponse("Unsupported item type", status=400)
    try:
        node = get_object_or_404(
            FileNode, pk=request.POST.get(f"{item_type}_id"), kind=item_type.upper()
        )
        target_id = request.POST.get("target_folder_id")
        target = (
            get_object_or_404(FileNode, pk=target_id, kind="FOLDER")
            if target_id and target_id != "None"
            else None
        )
    except (ValueError, ValidationError):
        return HttpResponse("Invalid node identity", status=400)
    access = FileAccessManager(request.user)
    if (
        not access.can_mutate_file_node(node)
        or target is not None
        and not access.can_mutate_file_node(target)
    ):
        return HttpResponse(status=403)
    node.parent = target
    node.updated_by = request.user
    try:
        node.save(update_fields=["parent", "updated_by"])
    except ValidationError as error:
        return HttpResponse(error.messages[0], status=400)
    return HttpResponse(status=204)
