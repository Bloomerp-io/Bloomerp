"""Read and atomically save a referenced document template's default signing layout."""

from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.document_signing.access import can_prepare, get_signing_document_templates
from bloomerp.document_signing.preparation import (
    save_signing_default,
    signing_default_payload,
)
from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.files.file_node import FileNode
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.serializers.signing_layout import SaveSigningLayoutSerializer
from bloomerp.views.api.base import BaseBloomerpApiView


@router.register(
    path="api/document-signing/<str:file_id>/default-layout/",
    url_name="api_document_signing_default_layout",
)
class DefaultSigningLayoutApiView(BaseBloomerpApiView):
    """Keep source resolution, permissions, and all default-layout writes on the server."""

    permission_classes = (IsAuthenticated,)

    def resolve_source(
        self, request: Request, file_id: str, template_id: str
    ) -> tuple[FileNode, DocumentTemplate, UserPolicyManager]:
        """Resolve an authorized PDF and a template actually referenced by that file."""
        try:
            file = get_object_or_404(FileNode, pk=file_id, kind="FILE")
        except (DjangoValidationError, ValueError) as error:
            raise ValidationError("Invalid PDF identifier.") from error
        manager = UserPolicyManager(request.user)
        if not can_prepare(file, manager):
            raise PermissionDenied("You cannot prepare this file.")
        if file.metadata.extension != "pdf":
            raise ValidationError("Choose a PDF document.")
        for template in get_signing_document_templates(file, manager):
            if str(template.pk) == str(template_id):
                return file, template, manager
        raise PermissionDenied(
            "Choose an accessible document template referenced by this PDF."
        )

    def get(self, request: Request, file_id: str) -> Response:
        """Return readable revisions and the requested snapshot without mutating the draft."""
        _, template, manager = self.resolve_source(
            request, file_id, request.query_params.get("document_template_id", "")
        )
        try:
            layout_id = (
                UUID(request.query_params["layout_id"])
                if "layout_id" in request.query_params
                else None
            )
        except ValueError as error:
            raise ValidationError("Choose a valid layout revision.") from error
        return Response(signing_default_payload(template, manager, layout_id))

    def post(self, request: Request, file_id: str) -> Response:
        """Validate and save one complete revision using the ordinary session/SDK boundary."""
        serializer = SaveSigningLayoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file, template, manager = self.resolve_source(
            request, file_id, str(serializer.validated_data["document_template_id"])
        )
        try:
            payload = save_signing_default(
                file, template, manager, serializer.validated_data
            )
        except DjangoValidationError as error:
            raise ValidationError(
                getattr(error, "message_dict", error.messages)
            ) from error
        return Response(payload)
