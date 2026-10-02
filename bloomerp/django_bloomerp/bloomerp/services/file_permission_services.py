from django.db.models import Model
from django.http import HttpRequest

from bloomerp.models import ApplicationField, File, FileFolder
from bloomerp.permissions.manager import UserPolicyManager, create_permission_str


def get_file_linked_object(file: File) -> Model | None:
    """Resolve the canonical field owner, using the file browser's batched cache."""
    if "_linked_object" in file.__dict__:
        return file.__dict__["_linked_object"]
    reference = getattr(file, "field_reference", None)
    content_type = reference.application_field.content_type if reference is not None else file.content_type
    object_id = reference.object_id if reference is not None else file.object_id
    model = content_type.model_class() if content_type is not None else None
    if model is None or not object_id:
        return None
    return model._base_manager.filter(pk=object_id).first()


def prepare_file_linked_objects(files: list[File]) -> None:
    """Batch-load file owners once per model for labels, previews, and access checks."""
    scopes: dict[type[Model], set[str]] = {}
    owners: dict[int, tuple[type[Model], str]] = {}
    for index, file in enumerate(files):
        reference = getattr(file, "field_reference", None)
        content_type = reference.application_field.content_type if reference is not None else file.content_type
        object_id = reference.object_id if reference is not None else file.object_id
        model = content_type.model_class() if content_type is not None else None
        file.__dict__["_linked_object"] = None
        if model is not None and object_id:
            scopes.setdefault(model, set()).add(object_id)
            owners[index] = (model, object_id)
    objects: dict[tuple[type[Model], str], Model] = {}
    for model, ids in scopes.items():
        for obj in model._base_manager.filter(pk__in=ids):
            objects[(model, str(obj.pk))] = obj
    for index, key in owners.items():
        files[index].__dict__["_linked_object"] = objects.get(key)


def get_linked_object_files_field(linked_object: Model | None) -> ApplicationField | None:
    """Return the ApplicationField governing a linked object's files relation."""
    if linked_object is None:
        return None
    return ApplicationField.get_by_field(linked_object.__class__, "files")


def has_linked_file_permission(
    request: HttpRequest,
    linked_object: Model | None,
    operation: str,
    *,
    field_name: str = "files",
) -> bool:
    """Check row access and the specific field owning a linked file operation."""
    if linked_object is None:
        return False

    permission_manager = UserPolicyManager(request.user)
    if not permission_manager.has_access_to_object(
        linked_object,
        create_permission_str(linked_object, "view"),
    ):
        return False

    files_field = ApplicationField.get_by_field(linked_object.__class__, field_name)
    if files_field is None:
        return False
    return permission_manager.has_field_permission(
        files_field,
        create_permission_str(linked_object, operation),
    )


def user_can_view_file(request: HttpRequest, file: File) -> bool:
    """Return whether the request user may view a file in its linked scope."""
    if request.user.is_superuser:
        return True

    linked_object = get_file_linked_object(file)
    if linked_object is not None:
        return has_linked_file_permission(
            request,
            linked_object,
            "view",
            field_name=file.linked_field_name or "files",
        )

    if file.linked_content_type_id or file.linked_object_id:
        return False
    return UserPolicyManager(request.user).has_global_permission(
        File,
        create_permission_str(File, "view"),
    )


def user_can_mutate_file(
    request: HttpRequest,
    file: File,
    operations: tuple[str, ...],
) -> bool:
    """Return whether any requested mutation is allowed for a file."""
    if request.user.is_superuser:
        return True

    linked_object = get_file_linked_object(file)
    if linked_object is not None:
        return any(
            has_linked_file_permission(
                request,
                linked_object,
                operation,
                field_name=file.linked_field_name or "files",
            )
            for operation in operations
        )

    if file.linked_content_type_id or file.linked_object_id:
        return False
    permission_manager = UserPolicyManager(request.user)
    return any(
        permission_manager.has_global_permission(
            File, create_permission_str(File, operation)
        )
        for operation in operations
    )


def user_can_view_folder(request: HttpRequest, folder: FileFolder) -> bool:
    """Return whether the user can view a folder or anything nested within it."""
    if request.user.is_superuser or request.user.has_perm("bloomerp.view_file"):
        return True

    from bloomerp.services.file_services import get_folder_linked_object

    linked_object = get_folder_linked_object(folder)
    if linked_object is not None and has_linked_file_permission(
        request, linked_object, "view"
    ):
        return True

    if any(user_can_view_file(request, file) for file in folder.files.all()):
        return True

    children = FileFolder.objects.filter(parent=folder).prefetch_related("files")
    return any(user_can_view_folder(request, child) for child in children)
