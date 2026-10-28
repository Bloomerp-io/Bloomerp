"""Download original bytes with ordinary API authentication and current file access."""

from uuid import UUID

from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from bloomerp.files.access import FileAccessManager
from bloomerp.models.files.file_node import FileNode
from bloomerp.router import router
from bloomerp.views.api.base import BaseBloomerpApiView


class FileIdentitySerializer(serializers.Serializer):
    """Validate the existing file identifier without accepting storage paths or URLs."""

    file_id = serializers.UUIDField()


def accessible_file(request: Request, file_id: UUID) -> FileNode:
    """Hide absent and inaccessible files behind the same unavailable response."""
    file = (
        FileAccessManager(request.user)
        .get_queryset(FileNode.objects.all())
        .filter(pk=file_id)
        .first()
    )
    if file is None:
        raise NotFound("File unavailable")
    return file


@router.register(
    path="files/download/",
    route_type="api",
    url_name="api_file_download",
    name="Download original file",
)
class FileDownloadView(BaseBloomerpApiView):
    """Stream an original file without revealing its storage location."""

    permission_classes = (IsAuthenticated,)
    http_method_names = ("get", "options")

    @extend_schema(
        tags=["Files"],
        parameters=[FileIdentitySerializer],
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY},
    )
    def get(self, request: Request) -> FileResponse:
        """Reauthorize each download and force a private, safe attachment response."""
        serializer = FileIdentitySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        file = accessible_file(request, serializer.validated_data["file_id"])
        try:
            content = file.content.open("rb")
        except (FileNotFoundError, OSError) as error:
            raise NotFound("File unavailable") from error
        response = FileResponse(
            content,
            as_attachment=True,
            filename=file.name or "file",
            content_type=file.metadata.mime_type or "application/octet-stream",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
