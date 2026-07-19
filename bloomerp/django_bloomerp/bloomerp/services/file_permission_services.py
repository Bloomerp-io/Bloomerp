from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest

from bloomerp.models import ApplicationField, File
from bloomerp.permissions.manager import UserPermissionManager, create_permission_str


def get_file_linked_object(file: File):
    """Return the object linked to a file without trusting a stale generic relation."""
    if not file.content_type_id or not file.object_id:
        return None

    content_type = ContentType.objects.filter(pk=file.content_type_id).first()
    model = content_type.model_class() if content_type else None
    if model is None:
        return None
    return model._base_manager.filter(pk=file.object_id).first()


def get_linked_object_files_field(linked_object) -> ApplicationField | None:
    """Return the ApplicationField governing a linked object's files relation."""
    if linked_object is None:
        return None
    return ApplicationField.get_by_field(linked_object.__class__, "files")


def has_linked_file_permission(
    request: HttpRequest,
    linked_object,
    operation: str,
) -> bool:
    """Check both row and files-field access for a linked file operation."""
    if linked_object is None:
        return False

    permission_manager = UserPermissionManager(request.user)
    if not permission_manager.has_access_to_object(
        linked_object,
        create_permission_str(linked_object, "view"),
    ):
        return False

    files_field = get_linked_object_files_field(linked_object)
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
        return has_linked_file_permission(request, linked_object, "view")

    return UserPermissionManager(request.user).has_global_permission(
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
            has_linked_file_permission(request, linked_object, operation)
            for operation in operations
        )

    permission_manager = UserPermissionManager(request.user)
    return any(
        permission_manager.has_global_permission(File, create_permission_str(File, operation))
        for operation in operations
    )
