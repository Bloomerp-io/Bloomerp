"""SDK-backed persistence of generic preparation roles and positioned fields."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.document_signing.access import can_prepare
from bloomerp.document_signing.preparation import preparation_payload, save_preparation
from bloomerp.models.document_signing import SignaturePreparation
from bloomerp.models.files.file_node import FileNode
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.serializers.signing_preparation import SaveSigningPreparationSerializer
from bloomerp.views.api.base import BaseBloomerpApiView


@router.register(
    path="api/document-signing/<str:file_id>/preparation/",
    url_name="api_document_signing_preparation",
)
class SigningPreparationApiView(BaseBloomerpApiView):
    """Save draft configuration without creating a request or concrete recipients."""

    permission_classes = (IsAuthenticated,)

    def get_file(self, request: Request, file_id: str) -> FileNode:
        """Require ordinary read access to the immutable PDF being prepared."""
        try:
            file = get_object_or_404(FileNode, pk=file_id, kind="FILE")
        except (DjangoValidationError, ValueError) as error:
            raise ValidationError("Invalid PDF identifier.") from error
        if not can_prepare(file, UserPolicyManager(request.user)):
            raise PermissionDenied("You cannot prepare this file.")
        if file.metadata.extension != "pdf":
            raise ValidationError("Choose a PDF document.")
        return file

    def get(self, request: Request, file_id: str) -> Response:
        """Return a policy-authorized preparation belonging to this exact PDF."""
        file = self.get_file(request, file_id)
        manager = UserPolicyManager(request.user)
        preparations = manager.get_accessible_queryset(
            SignaturePreparation, BloomerpPermission.VIEW
        ).filter(original_file=file)
        try:
            preparation = get_object_or_404(
                preparations, pk=request.query_params.get("preparation_id")
            )
        except (DjangoValidationError, ValueError) as error:
            raise ValidationError("Invalid preparation identifier.") from error
        return Response(preparation_payload(preparation, manager))

    def post(self, request: Request, file_id: str) -> Response:
        """Validate and save the entire preparation with one atomic SDK request."""
        file = self.get_file(request, file_id)
        serializer = SaveSigningPreparationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = save_preparation(
                file, UserPolicyManager(request.user), serializer.validated_data
            )
        except DjangoValidationError as error:
            raise ValidationError(
                getattr(error, "message_dict", error.messages)
            ) from error
        except IntegrityError as error:
            raise ValidationError(
                "The preparation changed elsewhere. Reload before saving again."
            ) from error
        return Response(payload)
