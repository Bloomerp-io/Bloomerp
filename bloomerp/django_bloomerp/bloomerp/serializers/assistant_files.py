"""Shared upload/link request and file-placement response serializers."""

import base64
import binascii
from pathlib import PurePosixPath
from typing import Any

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import serializers


class FileDestinationSerializer(serializers.Serializer):
    """Accept an optional, complete object identity."""

    model_label = serializers.CharField(required=False, max_length=255)
    object_id = serializers.CharField(required=False, max_length=36)

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
        if "folder_id" in self.initial_data:
            raise serializers.ValidationError(
                {"folder_id": "Folder placement is no longer supported for uploads"}
            )
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
    model_label = serializers.CharField(max_length=255)
    object_id = serializers.CharField(max_length=100)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Reject physical placement and require an object reference destination."""
        if "folder_id" in self.initial_data:
            raise serializers.ValidationError(
                {"folder_id": "Provide an object destination"}
            )
        return super().validate(attrs)


class UploadedFilePlacementSerializer(serializers.Serializer):
    """Return the new node identity and its optional object reference destination."""

    file_id = serializers.UUIDField()
    name = serializers.CharField()
    model_label = serializers.CharField(allow_null=True)
    object_id = serializers.CharField(allow_null=True)


class FilePlacementSerializer(serializers.Serializer):
    """Confirm the resulting file and its destination without returning its contents."""

    file_id = serializers.UUIDField()
    name = serializers.CharField(allow_null=True)
    model_label = serializers.CharField(allow_null=True)
    object_id = serializers.CharField(allow_null=True)
