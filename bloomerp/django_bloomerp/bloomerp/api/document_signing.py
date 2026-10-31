"""Draft-only guards layered onto the generated signing SDK resources."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.db.models import QuerySet
from django.db.models.deletion import ProtectedError, RestrictedError
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.serializers import BaseSerializer

from bloomerp.files.access import FileAccessManager
from bloomerp.filters.manager import ModelFilterManager
from bloomerp.models.document_signing import (
    SignatureRecipient,
    SignatureRequest,
    SignatureRequestField,
)
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.utils.api import ApiAccessResolver
from bloomerp.views.api.generic.base import BaseModelApiView

SIGNING_BUILDER_MODELS = (SignatureRequest, SignatureRecipient, SignatureRequestField)
BUILDER_FIELDS = {
    SignatureRequest: {"title", "original_file", "source_layout"},
    SignatureRecipient: {
        "request",
        "role_key",
        "role_label",
        "name",
        "email",
        "signing_order",
    },
    SignatureRequestField: {
        "request",
        "recipient",
        "key",
        "field_type",
        "required",
        "page_number",
        "x",
        "y",
        "width",
        "height",
        "settings",
    },
}


class SigningBuilderApiView(BaseModelApiView):
    """Expose policy-authorized draft preparation without exposing signing transitions."""

    def filter_queryset(self, queryset: QuerySet) -> QuerySet:
        """Resolve the builder's parent FK directly before applying ordinary filters."""
        parameters = self.request.query_params.copy()
        parents = parameters.pop("request", [])
        try:
            if parents:
                if self.model is SignatureRequest or len(parents) != 1:
                    raise ValidationError({"request": "Choose one parent draft."})
                queryset = queryset.filter(request_id=parents[0])
            return ModelFilterManager(self.model).filter(parameters, queryset=queryset)
        except DjangoValidationError as error:
            raise ValidationError(
                getattr(error, "message_dict", error.messages)
            ) from error

    def get_queryset(self) -> QuerySet:
        """Scope all three resources to readable PDFs and accessible draft requests."""
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return queryset
        from bloomerp.models.files.file_node import FileNode

        readable = FileAccessManager(self.request.user).get_queryset(
            FileNode.objects.all()
        )
        action = "retrieve" if self.action in {"list", "retrieve"} else "partial_update"
        requests = (
            ApiAccessResolver(self.request)
            .get_queryset(SignatureRequest, action)
            .filter(
                status=SignatureRequest.Status.DRAFT,
                original_file_id__in=readable.values("pk"),
            )
        )
        if self.model is SignatureRequest:
            return queryset.filter(pk__in=requests.values("pk"))
        queryset = queryset.filter(request_id__in=requests.values("pk"))
        if self.model is SignatureRecipient:
            return queryset.order_by("signing_order", "datetime_created", "pk")
        return queryset

    def validate_builder_payload(self, serializer: BaseSerializer) -> None:
        """Reject non-builder fields and authorize the PDF or parent request on writes."""
        if isinstance(self.request.data, list):
            raise ValidationError("Save draft records individually.")
        denied = set(self.request.data) - BUILDER_FIELDS[self.model]
        if denied:
            raise ValidationError(
                {
                    field: "This field is not editable in the builder."
                    for field in denied
                }
            )
        data = serializer.validated_data
        if self.model is SignatureRequest:
            file = data.get("original_file") or getattr(
                serializer.instance, "original_file", None
            )
            if file is None or not FileAccessManager(
                self.request.user
            ).can_read_file_node(file):
                raise PermissionDenied("You cannot prepare this file.")
            if (
                serializer.instance is not None
                and file.pk != serializer.instance.original_file_id
            ):
                raise ValidationError(
                    {"original_file": "Start another draft for a different PDF."}
                )
            if file.metadata.extension != "pdf":
                raise ValidationError({"original_file": "Select a PDF document."})
            if "source_layout" in data:
                layout = data["source_layout"]
                if layout is not None and not UserPolicyManager(
                    self.request.user
                ).has_access_to_object(
                    layout, BloomerpPermission.VIEW, fields=["name", "revision"]
                ):
                    raise PermissionDenied("You cannot use this signing layout.")
                data["source_layout_name"] = layout.name if layout else ""
                data["source_layout_revision"] = layout.revision if layout else None
        else:
            parent = data.get("request") or getattr(
                serializer.instance, "request", None
            )
            if parent is None:
                raise ValidationError({"request": "Choose a draft request."})
            from bloomerp.models.files.file_node import FileNode

            readable = FileAccessManager(self.request.user).get_queryset(
                FileNode.objects.all()
            )
            allowed = ApiAccessResolver(self.request).get_queryset(
                SignatureRequest, "partial_update"
            )
            if not allowed.filter(
                pk=parent.pk, status="draft", original_file_id__in=readable.values("pk")
            ).exists():
                raise PermissionDenied("You cannot edit this signing draft.")

    def perform_create(self, serializer: BaseSerializer) -> None:
        """Create one authorized draft record with server-owned user stamps."""
        self.validate_builder_payload(serializer)
        try:
            serializer.save(created_by=self.request.user, updated_by=self.request.user)
        except DjangoValidationError as error:
            raise ValidationError(
                getattr(error, "message_dict", error.messages)
            ) from error

    def perform_update(self, serializer: BaseSerializer) -> None:
        """Keep draft updates inside the native preparation contract."""
        self.validate_builder_payload(serializer)
        try:
            serializer.save(updated_by=self.request.user)
        except DjangoValidationError as error:
            raise ValidationError(
                getattr(error, "message_dict", error.messages)
            ) from error

    def perform_destroy(self, instance: models.Model) -> None:
        """Return useful validation errors when draft cleanup encounters retained records."""
        try:
            instance.delete()
        except (DjangoValidationError, ProtectedError, RestrictedError) as error:
            raise ValidationError(str(error)) from error
