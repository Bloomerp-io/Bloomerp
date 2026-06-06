from __future__ import annotations

from typing import Iterable

from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Model

from bloomerp.models import ApplicationField, File
from bloomerp.models.base_bloomerp_model import FieldLayout
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str


FILES_FIELD_NAME = "files"
FILES_RELATION_FIELD_TYPE = "FilesRelationField"


def get_files_application_field(model: type[Model]) -> ApplicationField | None:
    field = ApplicationField.get_by_field(model, FILES_FIELD_NAME)
    if field is None or field.field_type != FILES_RELATION_FIELD_TYPE:
        return None
    return field


def layout_contains_files_field(layout: FieldLayout | None, files_field: ApplicationField) -> bool:
    if layout is None:
        return False
    return any(str(item.id) == str(files_field.pk) for row in layout.rows for item in row.items)


def can_attach_files_from_layout(
    *,
    model: type[Model],
    user,
    layout: FieldLayout | None,
    action: str,
) -> bool:
    files_field = get_files_application_field(model)
    if files_field is None:
        return False
    if not layout_contains_files_field(layout, files_field):
        return False
    permission_manager = UserPermissionManager(user)
    return permission_manager.has_field_permission(
        files_field,
        create_permission_str(model, action),
    )


def attach_uploaded_files_to_object(
    *,
    obj: Model,
    uploaded_files: Iterable[UploadedFile],
    user,
) -> list[File]:
    files = [uploaded for uploaded in uploaded_files if uploaded]
    if not files:
        return []

    content_type = ContentType.objects.get_for_model(obj.__class__)
    stamp_user = user if getattr(user, "is_authenticated", False) else None
    created_files: list[File] = []
    for uploaded in files:
        created_files.append(
            File.objects.create(
                file=uploaded,
                name=uploaded.name,
                persisted=True,
                content_type=content_type,
                object_id=str(obj.pk),
                created_by=stamp_user,
                updated_by=stamp_user,
            )
        )
    return created_files


def attach_uploaded_files_to_form_submission(
    *,
    form_submission: Model,
    request,
    target_model: type[Model] | None,
    layout: FieldLayout | None,
) -> list[File]:
    if target_model is None:
        return []

    files_field = get_files_application_field(target_model)
    if files_field is None or not layout_contains_files_field(layout, files_field):
        return []

    request_files = getattr(request, "FILES", None)
    if request_files is None or not hasattr(request_files, "getlist"):
        return []

    return attach_uploaded_files_to_object(
        obj=form_submission,
        uploaded_files=request_files.getlist(FILES_FIELD_NAME),
        user=getattr(request, "user", None),
    )


def move_files_to_object(
    *,
    files: Iterable[File],
    obj: Model,
    user=None,
) -> list[File]:
    content_type = ContentType.objects.get_for_model(obj.__class__)
    stamp_user = user if getattr(user, "is_authenticated", False) else None
    moved_files: list[File] = []
    for file in files:
        file.content_type = content_type
        file.object_id = str(obj.pk)
        file.folder = None
        file.persisted = True
        if stamp_user is not None:
            file.updated_by = stamp_user
            if file.created_by_id is None:
                file.created_by = stamp_user
        file.save()
        moved_files.append(file)
    return moved_files


def move_form_submission_files_to_object(
    *,
    form_submission: Model,
    obj: Model,
    user=None,
) -> list[File]:
    file_ids = []
    if isinstance(getattr(form_submission, "data", None), dict):
        file_ids = form_submission.data.get(FILES_FIELD_NAME) or []

    files = list(form_submission.files.all())
    if file_ids:
        files_by_id = {str(file.id): file for file in files}
        files = [files_by_id[str(file_id)] for file_id in file_ids if str(file_id) in files_by_id]

    return move_files_to_object(
        files=files,
        obj=obj,
        user=user,
    )


def save_layout_uploaded_files(
    *,
    obj: Model,
    request,
    layout: FieldLayout | None,
    action: str,
) -> list[File]:
    if not can_attach_files_from_layout(
        model=obj.__class__,
        user=request.user,
        layout=layout,
        action=action,
    ):
        return []

    return attach_uploaded_files_to_object(
        obj=obj,
        uploaded_files=request.FILES.getlist(FILES_FIELD_NAME),
        user=request.user,
    )
