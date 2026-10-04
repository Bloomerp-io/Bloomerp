"""Small API/MCP contracts for uploading and placing files."""

import base64
import binascii
from pathlib import PurePosixPath
from typing import Any

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.mcp.definition import McpTool
from bloomerp.mcp.schema import serializer_input_schema, serializer_output_schema
from bloomerp.router import router
from bloomerp.services.assistant_file_services import (
    describe_file_placement,
    link_assistant_file,
    upload_assistant_file,
)
from bloomerp.views.api.base import BaseBloomerpApiView


class FileDestinationSerializer(serializers.Serializer):
    """Accept portable object identities and optional folder placement."""

    model_label = serializers.CharField(required=False, max_length=255)
    object_id = serializers.CharField(required=False, max_length=36)
    folder_id = serializers.IntegerField(required=False, min_value=1)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Require complete object identities before any upload or database mutation."""
        if bool(attrs.get("model_label")) != bool(attrs.get("object_id")):
            raise serializers.ValidationError(
                "Provide model_label and object_id together"
            )
        return attrs


class UploadFileSerializer(FileDestinationSerializer):
    """Accept multipart bytes or explicitly named base64 content for JSON MCP clients."""

    file = serializers.FileField(required=False, max_length=100)
    filename = serializers.CharField(required=False, max_length=100)
    content_base64 = serializers.CharField(required=False, trim_whitespace=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate byte size and filename before decoding or persisting an upload."""
        attrs = super().validate(attrs)
        if ("file" in attrs) == ("content_base64" in attrs):
            raise serializers.ValidationError("Provide either file or content_base64")
        limit = getattr(settings, "BLOOMERP_AGENT_UPLOAD_MAX_BYTES", 20 * 1024 * 1024)
        name = attrs.pop("filename", None)
        if "content_base64" in attrs:
            encoded = attrs.pop("content_base64")
            if not name:
                raise serializers.ValidationError(
                    "filename is required with content_base64"
                )
            if len(encoded) > 4 * ((limit + 2) // 3):
                raise serializers.ValidationError("File exceeds the upload size limit")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as error:
                raise serializers.ValidationError(
                    "Invalid base64 file content"
                ) from error
            attrs["file"] = SimpleUploadedFile(name, data)
        upload = attrs["file"]
        name = name or upload.name
        if name in {".", ".."} or PurePosixPath(name).name != name or "\\" in name:
            raise serializers.ValidationError(
                "filename must be a basename without directory components"
            )
        if not upload.size or upload.size > limit:
            raise serializers.ValidationError(
                f"File must be between 1 and {limit} bytes"
            )
        upload.name = name
        return attrs


class LinkFileSerializer(FileDestinationSerializer):
    """Identify an already uploaded file without resending its bytes."""

    file_id = serializers.UUIDField()


class FilePlacementSerializer(serializers.Serializer):
    """Confirm the resulting file and its destination without returning its contents."""

    file_id = serializers.UUIDField()
    name = serializers.CharField(allow_null=True)
    model_label = serializers.CharField(allow_null=True)
    object_id = serializers.CharField(allow_null=True)
    folder_id = serializers.IntegerField(allow_null=True)


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
            "to an object with model_label and object_id, or place in folder_id. "
            "A scoped folder supplies its object identity; explicit object and folder must match. "
            "For a file already uploaded or attached to this chat, use api_assistant_file_link "
            "with its file_id instead of uploading again."
        ),
        input_schema=upload_input_schema,
        output_schema=serializer_output_schema(FilePlacementSerializer),
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
class AssistantFileUploadView(BaseBloomerpApiView):
    """Upload to the file library or directly to an authorized object/folder."""

    permission_classes = (IsAuthenticated,)
    http_method_names = ("post", "options")

    def post(self, request: Request) -> Response:
        """Validate JSON or multipart content and return the created file's placement."""
        serializer = UploadFileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        file = upload_assistant_file(request, data.pop("file"), **data)
        return Response(describe_file_placement(file), status=201)


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

    permission_classes = (IsAuthenticated,)
    http_method_names = ("post", "options")

    def post(self, request: Request) -> Response:
        """Check source and target permissions and atomically update the existing file."""
        serializer = LinkFileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file = link_assistant_file(request, **serializer.validated_data)
        return Response(describe_file_placement(file))
