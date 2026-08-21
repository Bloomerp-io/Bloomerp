from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse

from bloomerp.components.files import (
    _check_linked_file_permission,
    _coerce_query_value,
    _get_linked_object_files_field,
    _get_object_scope,
    _get_target_folder,
)
from bloomerp.models import FileFolder
from bloomerp.router import router


@router.register(path="components/files/folders/create/", name="components_files_create_folder")
@login_required
def create_file_folder(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    content_type_id = _coerce_query_value(request.POST.get("content_type_id"))
    object_id = _coerce_query_value(request.POST.get("object_id"))
    parent_folder = _get_target_folder(
        _coerce_query_value(request.POST.get("parent_folder_id"))
    )

    linked_content_type, linked_object = _get_object_scope(content_type_id, object_id)
    files_field = _get_linked_object_files_field(linked_object) if linked_object else None

    if linked_object:
        if not _check_linked_file_permission(
            request=request,
            linked_object=linked_object,
            files_field=files_field,
            operation="add",
        ):
            return HttpResponse(status=403)
    elif not request.user.has_perm("bloomerp.add_filefolder"):
        return HttpResponse(status=403)

    name = (request.POST.get("name") or "").strip()
    if not name:
        return HttpResponse("Folder name is required", status=400)

    folder_content_type = linked_content_type or (
        parent_folder.content_type if parent_folder else None
    )
    folder_object_id = (
        str(linked_object.pk)
        if linked_object
        else (parent_folder.object_id if parent_folder else None)
    )

    folder = FileFolder(
        name=name,
        parent=parent_folder,
        content_type=folder_content_type,
        object_id=folder_object_id,
        created_by=request.user,
        updated_by=request.user,
    )
    try:
        folder.save()
    except ValidationError as exc:
        return HttpResponse(exc.messages[0], status=400)
    return JsonResponse({"ok": True, "folder_id": folder.id, "name": folder.name})
