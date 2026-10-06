"""Link existing files through the API and MCP using portable destination IDs."""

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.mcp.definition import McpTool
from bloomerp.mcp.schema import serializer_input_schema, serializer_output_schema
from bloomerp.router import router
from bloomerp.serializers.assistant_files import FilePlacementSerializer, LinkFileSerializer
from bloomerp.services.assistant_file_services import describe_file_placement, link_assistant_file
from bloomerp.views.api.base import BaseBloomerpApiView


@router.register(
    path="files/link/",
    route_type="api",
    name="Link an existing file",
    url_name="api_assistant_file_link",
    mcp=McpTool(
        title="Link an existing file",
        description=(
            "Attach an already uploaded file using its file_id (including a chat file artifact). "
            "Provide model_label and object_id to attach it to that object's files, folder_id "
            "to place it in a folder, or both for an object subfolder. A scoped folder supplies "
            "the object identity. This replaces the file's previous object/folder placement; "
            "it does not copy bytes. Files owned by dedicated fields cannot be reassigned."
        ),
        input_schema=serializer_input_schema(LinkFileSerializer),
        output_schema=serializer_output_schema(FilePlacementSerializer),
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
class AssistantFileLinkView(BaseBloomerpApiView):
    """Relocate a generic file without requiring internal content-type IDs."""

    serializer_class = LinkFileSerializer
    permission_classes = (IsAuthenticated,)
    http_method_names = ("post", "options")

    @extend_schema(
        tags=["Assistant"],
        request=LinkFileSerializer,
        responses={200: FilePlacementSerializer},
    )
    def post(self, request: Request) -> Response:
        """Check source and target permissions and atomically update the existing file."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file = link_assistant_file(request, **serializer.validated_data)
        return Response(describe_file_placement(file))

    def get_serializer(self, *args: Any, **kwargs: Any) -> LinkFileSerializer:
        """Expose file and destination identities to DRF metadata and schema discovery."""
        return self.serializer_class(*args, **kwargs)
