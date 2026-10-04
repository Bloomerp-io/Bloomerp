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

from bloomerp.models import File, FileFolder
from bloomerp.permissions.manager import UserPolicyManager, create_permission_str
from bloomerp.services.file_permission_services import (
    user_can_mutate_file,
    user_can_view_file,
    user_can_view_folder,
)


def require_object_files_access(
    request: HttpRequest, obj: Model, operation: str
) -> None:
    """Enforce object visibility and row-sensitive access to its files field."""
    manager = UserPolicyManager(request.user)
    if not manager.has_access_to_object(obj, create_permission_str(obj, "view")):
        raise PermissionDenied("Object unavailable")
    if (
        not manager.get_accessible_fields_for_object(
            obj, create_permission_str(obj, operation)
        )
        .filter(field="files")
        .exists()
    ):
        raise PermissionDenied("Permission to attach files to this object is required")


def resolve_destination(
    request: HttpRequest,
    *,
    model_label: str | None = None,
    object_id: str | None = None,
    folder_id: int | None = None,
) -> tuple[ContentType | None, str | None, FileFolder | None]:
    """Resolve and authorize one object/folder destination without exposing arbitrary models."""
    content_type = None
    obj = None
    if bool(model_label) != bool(object_id):
        raise ValidationError("Provide model_label and object_id together")
    if model_label:
        try:
            model = apps.get_model(model_label)
            field = model._meta.get_field("files")
            if (
                not isinstance(field, GenericRelation)
                or field.related_model is not File
            ):
                raise ValueError("Unsupported files field")
        except (LookupError, ValueError, AttributeError, FieldDoesNotExist) as error:
            raise ValidationError(
                "Unknown model or model does not support files"
            ) from error
        try:
            obj = get_object_or_404(model, pk=object_id)
        except (ValueError, DjangoValidationError) as error:
            raise ValidationError("Invalid object_id") from error
        content_type = ContentType.objects.get_for_model(model)
    folder = get_object_or_404(FileFolder, pk=folder_id) if folder_id else None
    if folder:
        if not user_can_view_folder(request, folder):
            raise PermissionDenied("Folder unavailable")
        if obj is not None and (
            folder.content_type_id != content_type.pk or folder.object_id != str(obj.pk)
        ):
            raise ValidationError("Folder and object must have the same scope")
        if obj is None:
            content_type = folder.content_type
            if folder.object_id:
                model = content_type.model_class() if content_type else None
                if model is None:
                    raise ValidationError("Folder object is unavailable")
                obj = get_object_or_404(model, pk=folder.object_id)
    if obj is not None:
        require_object_files_access(request, obj, "add")
    else:
        if content_type is not None:
            raise ValidationError(
                "Choose an object folder or a folder in the general file library"
            )
        manager = UserPolicyManager(request.user)
        if not manager.has_global_permission(
            File, "add_file"
        ) or not manager.has_global_permission(File, "view_file"):
            raise PermissionDenied(
                "File add and view permissions are required for this destination"
            )
    return content_type, str(obj.pk) if obj is not None else None, folder


def describe_file_placement(file: File) -> dict[str, Any]:
    """Return compact identifiers confirming the file's current canonical placement."""
    model = file.content_type.model_class() if file.content_type else None
    return {
        "file_id": str(file.pk),
        "name": file.name,
        "model_label": model._meta.label if model else None,
        "object_id": file.object_id,
        "folder_id": file.folder_id,
    }


def upload_assistant_file(
    request: HttpRequest, upload: UploadedFile, **destination: Any
) -> File:
    """Authorize placement before writing bytes and clean storage after failed persistence."""
    content_type, object_id, folder = resolve_destination(request, **destination)
    record = File(
        file=upload,
        name=upload.name,
        persisted=True,
        content_type=content_type,
        object_id=object_id,
        folder=folder,
        created_by=request.user,
        updated_by=request.user,
    )
    try:
        with transaction.atomic():
            record.save()
    except Exception:
        if record.file and record.file._committed:
            record.file.delete(save=False)
        raise
    return record


@transaction.atomic
def link_assistant_file(
    request: HttpRequest, file_id: UUID, **destination: Any
) -> File:
    """Move one existing generic file after checking both source and destination access."""
    file = get_object_or_404(
        File.objects.select_for_update(), pk=file_id, persisted=True
    )
    if not user_can_view_file(request, file) or not user_can_mutate_file(
        request, file, ("change",)
    ):
        raise PermissionDenied("File unavailable or cannot be changed")
    if getattr(file, "field_reference", None) is not None:
        raise ValidationError(
            "This file belongs to a dedicated field; update that field instead"
        )
    if file.linked_object is not None:
        require_object_files_access(request, file.linked_object, "view")
        require_object_files_access(request, file.linked_object, "change")
    if not destination.get("model_label") and not destination.get("folder_id"):
        raise ValidationError("Provide an object or folder destination")
    content_type, object_id, folder = resolve_destination(request, **destination)
    file.content_type, file.object_id, file.folder = content_type, object_id, folder
    file.updated_by = request.user
    file.save()
    return file
