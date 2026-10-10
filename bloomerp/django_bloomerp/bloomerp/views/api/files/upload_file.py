"""Upload files through the API and MCP using the same validated contract."""

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.mcp.definition import McpTool
from bloomerp.mcp.schema import serializer_input_schema, serializer_output_schema
from bloomerp.router import router
from bloomerp.serializers.assistant_files import (
    UploadedFilePlacementSerializer,
    UploadFileSerializer,
)
from bloomerp.services.assistant_file_services import (
    describe_uploaded_file,
    upload_assistant_file,
)
from bloomerp.views.api.base import BaseBloomerpApiView


def upload_input_schema() -> dict[str, Any]:
    """Describe JSON upload inputs while reserving multipart file for direct API clients."""
    schema = serializer_input_schema(UploadFileSerializer)
    schema["properties"].pop("file", None)
    schema["required"] = ["filename", "content_base64"]
    return schema


@router.register(
    path="files/upload/",
    route_type="api",
    name="Upload a file",
    url_name="api_assistant_file_upload",
    mcp=McpTool(
        title="Upload a file",
        description=(
            "Upload new file bytes using filename and content_base64. Optionally attach "
            "to an object with model_label and object_id, creating a file reference. "
            "Omit the object identity to upload without a reference."
        ),
        input_schema=upload_input_schema,
        output_schema=serializer_output_schema(UploadedFilePlacementSerializer),
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
class AssistantFileUploadView(BaseBloomerpApiView):
    """Create a file node and optionally reference an authorized object."""

    serializer_class = UploadFileSerializer
    permission_classes = (IsAuthenticated,)
    http_method_names = ("post", "options")

    @extend_schema(
        tags=["Assistant"],
        request=UploadFileSerializer,
        responses={201: UploadedFilePlacementSerializer},
    )
    def post(self, request: Request) -> Response:
        """Validate JSON or multipart content and return the created file's placement."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        file = upload_assistant_file(request, data.pop("file"), **data)
        return Response(describe_uploaded_file(file), status=201)

    def get_serializer(self, *args: Any, **kwargs: Any) -> UploadFileSerializer:
        """Expose upload fields to request validation, DRF metadata and schema discovery."""
        return self.serializer_class(*args, **kwargs)
