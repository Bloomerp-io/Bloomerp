"""Permission-checked upload and placement of assistant files without schema discovery."""

from typing import Any
from uuid import UUID

from django.apps import apps
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Model
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError

from bloomerp.files.access import FileAccessManager
from bloomerp.models.files.file_node import FileNode
from bloomerp.models.files.file_reference import FileReference
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager


def require_object_files_access(
    request: HttpRequest, obj: Model, operation: BloomerpPermission
) -> None:
    """Enforce object visibility and row-sensitive access to its files field."""
    if not FileAccessManager(request.user).has_access_to_linked_object(obj, operation):
        raise PermissionDenied("Permission to access this object's files is required")


def resolve_upload_target(
    request: HttpRequest, *, model_label: str | None, object_id: str | None
) -> Model | None:
    """Authorize an optional reference target before storing any uploaded bytes."""
    if bool(model_label) != bool(object_id):
        raise ValidationError("Provide model_label and object_id together")
    if model_label:
        try:
            model = apps.get_model(model_label)
            field = model._meta.get_field("files")
            if (
                not isinstance(field, GenericRelation)
                or field.related_model is not FileReference
            ):
                raise TypeError("Unsupported files field")
        except (
            LookupError,
            ValueError,
            TypeError,
            AttributeError,
            FieldDoesNotExist,
        ) as error:
            raise ValidationError(
                "Unknown model or model does not support files"
            ) from error
        try:
            obj = get_object_or_404(model, pk=object_id)
        except (ValueError, DjangoValidationError) as error:
            raise ValidationError("Invalid object_id") from error
        require_object_files_access(request, obj, BloomerpPermission.ADD)
        return obj
    manager = UserPolicyManager(request.user)
    if not all(
        manager.has_global_permission(FileNode, permission)
        for permission in (BloomerpPermission.ADD, BloomerpPermission.VIEW)
    ):
        raise PermissionDenied("File node add and view permissions are required")
    return None


def upload_assistant_file(
    request: HttpRequest,
    upload: UploadedFile,
    *,
    model_label: str | None = None,
    object_id: str | None = None,
) -> FileNode:
    """Save uploaded bytes and an optional reference atomically, cleaning failed writes."""
    target = resolve_upload_target(
        request, model_label=model_label, object_id=object_id
    )
    record = FileNode(
        content=upload,
        kind="FILE",
        name=upload.name,
        created_by=request.user,
        updated_by=request.user,
    )
    try:
        with transaction.atomic():
            record.save()
            if target is not None:
                FileReference.objects.create(
                    file=record,
                    content_object=target,
                    created_by=request.user,
                    updated_by=request.user,
                )
    except Exception:
        if record.content and record.content._committed:
            record.content.delete(save=False)
        raise
    return record


def describe_uploaded_file(file: FileNode) -> dict[str, Any]:
    """Describe a newly uploaded node and the optional reference created with it."""
    reference = file.references.select_related("content_type").first()
    return {
        "file_id": str(file.pk),
        "name": file.name,
        "model_label": (
            reference.content_type.model_class()._meta.label if reference else None
        ),
        "object_id": reference.object_id if reference else None,
    }


@transaction.atomic
def link_assistant_file(
    request: HttpRequest, file_id: UUID, *, model_label: str, object_id: str
) -> FileNode:
    """Add an idempotent object reference without moving bytes or existing references."""
    file = get_object_or_404(
        FileNode.objects.select_for_update(), pk=file_id, kind="FILE"
    )
    if not FileAccessManager(request.user).can_read_file_node(file):
        raise PermissionDenied("File unavailable")
    target = resolve_upload_target(
        request, model_label=model_label, object_id=object_id
    )
    if target is None:
        raise ValidationError("Provide an object destination")
    reference, _ = FileReference.objects.get_or_create(
        file=file,
        content_type=ContentType.objects.get_for_model(target),
        object_id=str(target.pk),
        application_field=None,
        occurrence_id=None,
        defaults={"created_by": request.user, "updated_by": request.user},
    )
    file._linked_reference = reference
    return file


def describe_file_placement(file: FileNode) -> dict[str, Any]:
    """Describe the reference selected by the link operation, even for shared files."""
    reference = file._linked_reference
    return {
        "file_id": str(file.pk),
        "name": file.name,
        "model_label": reference.content_type.model_class()._meta.label,
        "object_id": reference.object_id,
    }
