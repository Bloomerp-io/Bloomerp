"""Search, upload and render file references through existing library permissions."""

import mimetypes
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import UploadedFile
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from pydantic import Field

from bloomerp.agents.definition import (
    AIArtifactDescription,
    AIArtifactPayload,
    AIArtifactRenderer,
    AIArtifactSearchPage,
    AIArtifactSearchRequest,
    AIArtifactTypeDefinition,
)


class FileArtifactPayload(AIArtifactPayload):
    """Identify a file source without copying its live content or permissions."""

    file_id: UUID
    name: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=255)


def describe_file(payload: FileArtifactPayload) -> AIArtifactDescription:
    """Describe the reference without fetching content or asserting target access."""
    return AIArtifactDescription(
        title=payload.name,
        summary=(
            f"Attached file {payload.file_id} ({payload.media_type}); "
            "use api_assistant_file_link with this file_id to attach it to an object "
            "without uploading it again. Use a file-reading tool to inspect its contents."
        ),
    )


def authorize_file(payload: FileArtifactPayload, request: HttpRequest) -> None:
    """Use existing linked-object and file-library permissions at every read boundary."""
    from bloomerp.files.access import FileAccessManager
    from bloomerp.models.files.file_node import FileNode

    file = FileNode.objects.filter(pk=payload.file_id).first()
    if file is None or not FileAccessManager(request.user).can_read_file_node(file):
        raise PermissionDenied("File unavailable")


def file_reference(payload: FileArtifactPayload) -> UUID:
    """Connect selected metadata to the existing relational FileNode reference."""
    return payload.file_id


def search_files(
    request: HttpRequest, search: AIArtifactSearchRequest
) -> AIArtifactSearchPage[FileArtifactPayload]:
    """Scan a bounded file page, filtering inaccessible files before returning metadata."""
    from bloomerp.files.access import FileAccessManager
    from bloomerp.models.files.file_node import FileNode

    query = FileNode.objects.filter(kind="FILE").order_by("pk")
    if search.query:
        query = query.filter(name__icontains=search.query)
    if search.cursor:
        query = query.filter(pk__gt=UUID(search.cursor))
    rows = list(query[:201])
    items = []
    cursor = None
    for index, file in enumerate(rows[:200]):
        cursor = str(file.pk)
        if FileAccessManager(request.user).can_read_file_node(file):
            items.append(
                FileArtifactPayload(
                    file_id=file.pk,
                    name=file.name or Path(file.content.name).name,
                    media_type=file.meta.get("mime_type") or "application/octet-stream",
                )
            )
        if len(items) == search.limit:
            return AIArtifactSearchPage(
                items=items, cursor=cursor if index + 1 < len(rows) else None
            )
    return AIArtifactSearchPage(items=items, cursor=cursor if len(rows) > 200 else None)


def upload_file(request: HttpRequest, file: UploadedFile) -> FileArtifactPayload:
    """Store one size-limited upload using normal file-library creation permissions."""
    from bloomerp.services.assistant_file_services import upload_assistant_file

    limit = getattr(settings, "BLOOMERP_AGENT_UPLOAD_MAX_BYTES", 20 * 1024 * 1024)
    if not file.size or file.size > limit:
        raise ValueError(f"File must be between 1 and {limit} bytes")
    name = Path(file.name).name
    if len(name) > 100:
        raise ValueError("Filename must contain at most 100 characters")
    from rest_framework.exceptions import PermissionDenied as ApiPermissionDenied

    try:
        record = upload_assistant_file(request, file)
    except ApiPermissionDenied as error:
        raise PermissionDenied(str(error.detail)) from error
    return FileArtifactPayload(
        file_id=record.pk,
        name=name,
        media_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
    )


class FileArtifactRenderer(AIArtifactRenderer[FileArtifactPayload]):
    """Render an attachment link without extracting or embedding untrusted file content."""

    @classmethod
    def render(
        cls, artifact_id: UUID, payload: FileArtifactPayload, request: HttpRequest
    ) -> str:
        """Provide an authorized download rather than leaking a raw storage URL."""
        authorize_file(payload, request)
        return format_html(
            '<a class="badge badge-secondary" href="{}"><strong>{}</strong><span class="block text-xs text-gray-500">{}</span></a>',
            reverse(
                "components_agent_download_file", kwargs={"file_id": payload.file_id}
            ),
            payload.name,
            payload.media_type,
        )


FILE_ARTIFACT = AIArtifactTypeDefinition[FileArtifactPayload](
    key="file",
    label="Files",
    model=FileArtifactPayload,
    describe=describe_file,
    icon="fa-file",
    authorize=authorize_file,
    search=search_files,
    upload=upload_file,
    selection_file_id=file_reference,
    render_cls=FileArtifactRenderer,
)
