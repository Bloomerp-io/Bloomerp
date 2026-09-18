from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.http import HttpRequest
from django.shortcuts import get_object_or_404

from bloomerp.models.files.file_folder import FileFolder

if TYPE_CHECKING:
    from bloomerp.models.files.file import File

# TODO: refactor the file manager logic


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
    return (
        FileFolder.objects.filter(
            content_type=content_type,
            object_id__isnull=True,
        )
        .order_by("id")
        .first()
    )


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

    defaults = {
        "created_by": created_by,
        "updated_by": updated_by,
        "protected": True,
    }

    model_folder = FileFolder.objects.filter(
        content_type=content_type,
        object_id__isnull=True,
    ).order_by("id").first()
    if model_folder is None:
        model_folder = FileFolder.objects.create(
            name=model_name,
            parent=None,
            content_type=content_type,
            created_by=created_by,
            updated_by=updated_by,
            protected=True,
        )

    module_folder, _ = FileFolder.objects.get_or_create(
        name=module_name,
        parent=None,
        defaults=defaults,
    )
    if not module_folder.protected:
        module_folder.protected = True
        module_folder.save(update_fields=["protected"])

    model_updates: list[str] = []
    if model_folder.parent_id != module_folder.id:
        model_folder.parent = module_folder
        model_updates.append("parent")
    if model_folder.content_type_id != content_type.id:
        model_folder.content_type = content_type
        model_updates.append("content_type")
    if model_folder.object_id is not None:
        model_folder.object_id = None
        model_updates.append("object_id")
    if not model_folder.protected:
        model_folder.protected = True
        model_updates.append("protected")
    if model_updates:
        model_folder.save(update_fields=model_updates)

    object_folder, _ = FileFolder.objects.get_or_create(
        name=object_name,
        parent=model_folder,
        defaults={
            **defaults,
            "content_type": content_type,
            "object_id": object_id,
        },
    )
    object_updates: list[str] = []
    if object_folder.name != object_name:
        object_folder.name = object_name
        object_updates.append("name")
    if object_folder.content_type_id != content_type.id:
        object_folder.content_type = content_type
        object_updates.append("content_type")
    if (object_folder.object_id or None) != object_id:
        object_folder.object_id = object_id
        object_updates.append("object_id")
    if object_folder.parent_id != model_folder.id:
        object_folder.parent = model_folder
        object_updates.append("parent")
    if not object_folder.protected:
        object_folder.protected = True
        object_updates.append("protected")
    if object_updates:
        object_folder.save(update_fields=object_updates)

    return object_folder
