"""Generic discovery and upload boundary for registered attachable artifact types."""

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from bloomerp.agents.definition import AIArtifactTypeDefinition

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from pydantic import ValidationError

from bloomerp.agents.artifacts.registry import AI_ARTIFACT_REGISTRY
from bloomerp.agents.artifacts.selection import selection_item
from bloomerp.agents.definition import AIArtifactSearchRequest
from bloomerp.router import router


@router.register(
    path="components/agents/search_artifacts/", url_name="components_search_artifacts"
)
@login_required
@never_cache
@require_GET
def search_artifacts(request: HttpRequest) -> HttpResponse:
    """List attachable types or dispatch a bounded search through a registered hook."""
    try:
        key = request.GET.get("type")
        if not key:
            latest = {}
            for definition in AI_ARTIFACT_REGISTRY.values():
                if (
                    definition.search is not None or definition.upload is not None
                ) and (
                    definition.key not in latest
                    or definition.schema_version > latest[definition.key].schema_version
                ):
                    latest[definition.key] = definition
            return JsonResponse(
                {
                    "types": [
                        {
                            "key": item.key,
                            "label": item.label,
                            "icon": item.icon,
                            "upload": item.upload is not None,
                        }
                        for item in latest.values()
                    ]
                }
            )
        versions = [item for item in AI_ARTIFACT_REGISTRY.values() if item.key == key]
        if not versions:
            return JsonResponse({"error": "Unknown artifact type"}, status=400)
        definition = max(versions, key=artifact_version)
        if definition.search is None:
            return JsonResponse({"items": [], "cursor": None})
        search = AIArtifactSearchRequest(
            query=request.GET.get("q", ""),
            cursor=request.GET.get("cursor") or None,
            limit=request.GET.get("limit", 20),
        )
        page = definition.search(request, search)
        return JsonResponse(
            {
                "items": [
                    selection_item(definition, payload, request)
                    for payload in page.items
                ],
                "cursor": page.cursor,
            }
        )
    except (ValueError, ValidationError):
        return JsonResponse({"error": "Invalid artifact search"}, status=400)


def artifact_version(definition: "AIArtifactTypeDefinition") -> int:
    """Select the latest schema for new user attachments."""
    return definition.schema_version


@router.register(
    path="components/agents/upload_artifact/", url_name="components_upload_artifact"
)
@login_required
@never_cache
@require_POST
def upload_artifact(request: HttpRequest) -> HttpResponse:
    """Delegate multipart uploads to the selected artifact type's authorized handler."""
    try:
        versions = [
            item
            for item in AI_ARTIFACT_REGISTRY.values()
            if item.key == request.POST.get("type")
        ]
        if not versions or len(request.FILES.getlist("file")) != 1:
            return JsonResponse(
                {"error": "Select one file and an upload type"}, status=400
            )
        definition = max(versions, key=artifact_version)
        if definition.upload is None:
            return JsonResponse(
                {"error": "This type does not accept uploads"}, status=400
            )
        payload = definition.upload(request, request.FILES["file"])
        return JsonResponse(selection_item(definition, payload, request))
    except PermissionDenied:
        return JsonResponse(
            {"error": "You do not have permission to upload this file"}, status=403
        )
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)


@router.register(
    path="components/agents/files/<uuid:file_id>/",
    url_name="components_agent_download_file",
)
@login_required
@never_cache
@require_GET
def download_file(request: HttpRequest, file_id: UUID) -> HttpResponse:
    """Serve authorized attachments with download disposition and no shared caching."""
    from bloomerp.files.access import FileAccessManager
    from bloomerp.models.files.file_node import FileNode

    file = get_object_or_404(FileNode, pk=file_id, kind="FILE")
    if not FileAccessManager(request.user).can_read_file_node(file):
        raise PermissionDenied("File unavailable")
    response = FileResponse(
        file.content.open("rb"), as_attachment=True, filename=file.name
    )
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
