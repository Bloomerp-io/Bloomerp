"""Serve stored file bytes after checking upload or reference access."""

from uuid import UUID

from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from bloomerp.files.access import FileAccessManager
from bloomerp.models import FileNode
from bloomerp.router import router


@router.register(path="files/serve", route_type="api", url_name="api_files_serve")
@require_GET
def serve_file(request: HttpRequest) -> HttpResponse:
    """Return private bytes only after resolving all current access grants."""
    try:
        file_id = UUID(request.GET.get("file_id", ""))
    except (ValueError, TypeError):
        return HttpResponse("Invalid file ID", status=400)
    file = get_object_or_404(FileNode, pk=file_id, kind="FILE")
    if not FileAccessManager(request.user).can_read_file_node(file):
        return HttpResponse("File unavailable", status=403)
    if not file.content:
        return HttpResponse("File unavailable", status=404)
    mime = file.metadata.mime_type or "application/octet-stream"
    inline = mime in {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/avif",
        "audio/mpeg",
        "audio/ogg",
        "video/mp4",
        "video/webm",
    }
    try:
        response = FileResponse(
            file.content.open("rb"),
            as_attachment=not inline,
            filename=file.name or "file",
            content_type=mime if inline else "application/octet-stream",
        )
    except FileNotFoundError:
        return HttpResponse("File unavailable", status=404)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
