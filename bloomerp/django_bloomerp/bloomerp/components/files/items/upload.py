"""Upload component attachments through the shared node/reference upload service."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from rest_framework.exceptions import APIException

from bloomerp.router import router
from bloomerp.services.assistant_file_services import (
    resolve_upload_target,
    upload_assistant_file,
)


@router.register(path="components/files/upload/", name="components_files_upload")
@login_required
def upload_files(request: HttpRequest) -> HttpResponse:
    """Store each upload with an optional complete object reference identity."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)
    if "folder_id" in request.POST or "content_type_id" in request.POST:
        return JsonResponse(
            {"error": "Use model_label and object_id; folder placement is unsupported"},
            status=400,
        )
    destination = {
        "model_label": request.POST.get("model_label") or None,
        "object_id": request.POST.get("object_id") or None,
    }
    files = request.FILES.getlist("files")
    if not files:
        return JsonResponse({"error": "Provide at least one file"}, status=400)
    try:
        resolve_upload_target(request, **destination)
        for uploaded in files:
            upload_assistant_file(request, uploaded, **destination)
    except APIException as error:
        return JsonResponse({"error": str(error.detail)}, status=error.status_code)
    return JsonResponse({"ok": True, "count": len(files)})
