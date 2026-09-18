from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404

from bloomerp.models.files.file_folder import FileFolder

if TYPE_CHECKING:
    from bloomerp.models.files.file import File

# TODO: refactor the file manager logic


def get_module_folder_scope_key(root_module, content_type: ContentType) -> str:
    module_id = (
        getattr(root_module, "full_id", None) or root_module.id
        if root_module
        else f"app:{content_type.app_label}"
    )
    return f"module:{module_id}"


def get_model_folder_scope_key(content_type: ContentType) -> str:
    return f"model:{content_type.app_label}.{content_type.model}"


def get_object_folder_scope_key(
    content_type: ContentType, object_id: object
) -> str:
    return f"object:{content_type.app_label}.{content_type.model}:{object_id}"


def _ensure_system_folder(
    *, kind: str, scope_key: str, values: dict
) -> FileFolder:
    folder, _ = FileFolder.objects.get_or_create(
        scope_key=scope_key,
        defaults={"kind": kind, **values},
    )

    changed_fields = []
    for field_name, value in values.items():
        if field_name in {"created_by", "updated_by"}:
            continue
        if getattr(folder, field_name) != value:
            setattr(folder, field_name, value)
            changed_fields.append(field_name)

    if changed_fields:
        folder.save(update_fields=changed_fields)

    return folder


class FileManager:
    def get_or_create_folders_for_object(self, object: models.Model) -> FileFolder:
        """
        This method creates folders for the given object if they don't already exist.
        The folder structure is based on the object's model and primary key.
        """
        return ensure_folder_hierarchy_for_object(object)


def coerce_file_scope_value(value: str | None) -> str | None:
    if value in {"", "None", None}:
        return None
    return value


def resolve_file_scope(content_type_id: str | None, object_id: str | None):
    if not content_type_id or not object_id:
        return None, None

    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return content_type, None

    return content_type, get_object_or_404(model, pk=object_id)


def get_folder_linked_object(folder: FileFolder):
    if folder.content_type is None or not folder.object_id:
        return None

    model = folder.content_type.model_class()
    if model is None:
        return None
    return model._base_manager.filter(pk=folder.object_id).first()


def get_target_folder(folder_id: str | None) -> FileFolder | None:
    if not folder_id:
        return None
    return get_object_or_404(FileFolder, id=folder_id)


def get_model_scope_folder(content_type: ContentType | None) -> FileFolder | None:
    if content_type is None:
        return None
    return FileFolder.objects.filter(
        kind=FileFolder.Kind.MODEL,
        scope_key=get_model_folder_scope_key(content_type),
    ).first()


def get_file_for_mutation(request: HttpRequest) -> File:
    from bloomerp.models.files.file import File
    from bloomerp.services.file_permission_services import user_can_mutate_file

    file = get_object_or_404(File, id=request.POST.get("file_id"))
    if not user_can_mutate_file(request, file, ("change", "add")):
        raise PermissionError
    return file


def get_folder_descendants(folder: FileFolder) -> tuple[list[FileFolder], list[File]]:
    from bloomerp.models.files.file import File

    folders: list[FileFolder] = []
    files: dict[str, File] = {}
    stack = [folder]

    while stack:
        current = stack.pop()
        folders.append(current)
        for file in current.files.all():
            files[str(file.id)] = file
        stack.extend(
            FileFolder.objects.filter(parent=current).prefetch_related("files")
        )

    return folders, list(files.values())


@transaction.atomic
def ensure_folder_hierarchy_for_object(
    linked_object: models.Model | None,
    *,
    created_by=None,
    updated_by=None,
) -> FileFolder | None:
    if linked_object is None:
        return None

    from bloomerp.modules.definition import module_registry

    content_type = ContentType.objects.get_for_model(linked_object)
    object_id = str(linked_object.pk)
    model = content_type.model_class()
    if model is None:
        return None

    module = module_registry.get_module_for_model(model)
    root_module = module_registry.get_root(module.full_id or module.id) if module else None
    module_name = root_module.name if root_module else content_type.app_label
    model_name = model._meta.verbose_name_plural
    object_name = str(linked_object)

    module_folder = _ensure_system_folder(
        kind=FileFolder.Kind.MODULE,
        scope_key=get_module_folder_scope_key(root_module, content_type),
        values={
            "name": module_name,
            "parent": None,
            "content_type": None,
            "object_id": None,
            "protected": True,
            "created_by": created_by,
            "updated_by": updated_by,
        },
    )
    model_folder = _ensure_system_folder(
        kind=FileFolder.Kind.MODEL,
        scope_key=get_model_folder_scope_key(content_type),
        values={
            "name": model_name,
            "parent": module_folder,
            "content_type": content_type,
            "object_id": None,
            "protected": True,
            "created_by": created_by,
            "updated_by": updated_by,
        },
    )
    object_folder = _ensure_system_folder(
        kind=FileFolder.Kind.OBJECT,
        scope_key=get_object_folder_scope_key(content_type, object_id),
        values={
            "name": object_name,
            "parent": model_folder,
            "content_type": content_type,
            "object_id": object_id,
            "protected": True,
            "created_by": created_by,
            "updated_by": updated_by,
        },
    )

    return object_folder
