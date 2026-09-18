from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse

from bloomerp.services.file_permission_services import has_linked_file_permission
from bloomerp.services.file_services import (
    coerce_file_scope_value,
    get_target_folder,
    resolve_file_scope,
)
from bloomerp.models import File
from bloomerp.router import router


@router.register(path="components/files/upload/", name="components_files_upload")
@login_required
def upload_files(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    content_type_id = coerce_file_scope_value(request.POST.get("content_type_id"))
    object_id = coerce_file_scope_value(request.POST.get("object_id"))
    folder_id = coerce_file_scope_value(request.POST.get("folder_id"))

    linked_content_type, linked_object = resolve_file_scope(content_type_id, object_id)
    requested_object_id = str(linked_object.pk) if linked_object else None

    if linked_object:
        if not has_linked_file_permission(request, linked_object, "add"):
            return HttpResponse(status=403)
    elif not request.user.has_perm("bloomerp.add_file"):
        return HttpResponse(status=403)

    target_folder = get_target_folder(folder_id)
    if target_folder and (
        target_folder.content_type_id != (linked_content_type.id if linked_content_type else None)
        or (target_folder.object_id or None) != requested_object_id
    ):
        return HttpResponse("Selected folder has a different scope", status=400)

    uploaded_files = request.FILES.getlist("files")
    for uploaded in uploaded_files:
        File.objects.create(
            file=uploaded,
            name=uploaded.name,
            persisted=True,
            content_type=linked_content_type,
            object_id=requested_object_id,
            folder=target_folder,
            created_by=request.user,
            updated_by=request.user,
        )

    return JsonResponse({"ok": True, "count": len(uploaded_files)})
