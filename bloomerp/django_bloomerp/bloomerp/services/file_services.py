

from django.db import models
from django.contrib.contenttypes.models import ContentType

from bloomerp.models.files.file_folder import FileFolder

# TODO: refactor the file manager logic

class FileManager:

    def get_or_create_folders_for_object(self, object: models.Model) -> FileFolder:
        """
        This method creates folders for the given object if they don't already exist.
        The folder structure is based on the object's model and primary key.
        """
        return ensure_folder_hierarchy_for_object(object)


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

    modules = module_registry.get_modules_for_model(model)
    module_name = modules[0].name if modules else content_type.app_label
    model_name = model._meta.verbose_name_plural
    object_name = str(linked_object)

    defaults = {
        "created_by": created_by,
        "updated_by": updated_by,
        "protected": True,
    }

    model_folder = FileFolder.objects.filter(
        name=model_name,
        content_type=content_type,
        object_id__isnull=True,
    ).first()
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
