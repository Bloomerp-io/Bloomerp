"""Authorize file bytes through current generic or field-specific references."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import models
from django.db.models import Model, Q
from django.http import HttpRequest

from bloomerp.models import ApplicationField, File, FileFolder
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.compilers.django_q_permission_compiler import (
    DjangoQPermissionCompiler,
)
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.utils.api import ApiAccessResolver

if TYPE_CHECKING:
    from bloomerp.models.files.file_node import FileNode


def can_read_object_field(
    request: HttpRequest, obj: models.Model, field_name: str
) -> bool:
    """Evaluate row-sensitive field grants, including configured anonymous API rules."""
    if request.user.is_superuser:
        return True
    resolver = ApiAccessResolver(request)
    compilation = DjangoQPermissionCompiler(
        resolver.get_applicable_access_rules(type(obj), "retrieve"),
        user=request.user,
        model=type(obj),
    ).compile("view")
    field_filter = Q(pk__in=[])
    for row_filter, fields in compilation.field_filters.items():
        if any(field.field == field_name for field in fields):
            field_filter |= row_filter
    return (
        type(obj)
        ._base_manager.filter(pk=obj.pk)
        .filter(compilation.row_filter)
        .filter(field_filter)
        .exists()
    )


class FileAccessManager:
    """Authorize file reads, mutations, and folder access through one permission service."""

    def __init__(self, user: Any) -> None:
        """Bind access decisions to the requesting user."""
        self.user: AbstractBloomerpUser = user

    def can_read_file_node(self, file: FileNode) -> bool:
        """Allow reading through an accessible reference or an unreferenced upload scope."""
        if file.kind != "FILE" or not file.content:
            return False
        # Import sources are private wizard state, never reusable library attachments.
        # BulkCrudService reads them directly with owner and destination-model checks.
        if file.meta.get("bulk_upload"):
            return False
        if self.user.is_superuser:
            return True
        request = HttpRequest()
        request.user = self.user
        references = list(
            file.references.select_related("content_type", "application_field")
        )
        for reference in references:
            obj = reference.content_object
            if obj is None:
                continue
            field_name = (
                reference.application_field.field
                if reference.application_field
                else "files"
            )
            if obj._meta.model_name == "comment" and reference.application_field:
                obj = obj.content_object
                field_name = "comments"
            if obj is not None and can_read_object_field(request, obj, field_name):
                return True
        if references:
            return False
        return self.user.is_authenticated and (
            file.created_by_id == self.user.pk
            or UserPolicyManager(self.user).has_global_permission(
                type(file), BloomerpPermission.VIEW
            )
        )

    def can_mutate_file_node(
        self, file: FileNode, operation: BloomerpPermission = BloomerpPermission.CHANGE
    ) -> bool:
        """Authorize node-wide changes across every reference affected by the operation."""
        if not self.user.is_authenticated:
            return False
        if self.user.is_superuser:
            return True
        if file.kind == "FOLDER":
            return UserPolicyManager(self.user).has_global_permission(
                type(file), operation
            )
        if not self.can_read_file_node(file):
            return False
        references = list(
            file.references.select_related("content_type", "application_field")
        )
        if not references:
            return file.created_by_id == self.user.pk or UserPolicyManager(
                self.user
            ).has_global_permission(type(file), operation)
        for reference in references:
            obj = reference.content_object
            field_name = (
                reference.application_field.field
                if reference.application_field
                else "files"
            )
            if (
                obj is not None
                and obj._meta.model_name == "comment"
                and reference.application_field
            ):
                obj, field_name = obj.content_object, "comments"
            if obj is None or not self.has_access_to_linked_object(
                obj, operation, field_name=field_name
            ):
                return False
        return True

    def has_access_to_file(
        self,
        file: File | None,
        permissions: BloomerpPermission
        | tuple[BloomerpPermission, ...] = BloomerpPermission.VIEW,
    ) -> bool:
        """Authorize any requested operation, preserving draft privacy and shared file bytes."""
        requested = (
            (permissions,)
            if isinstance(permissions, BloomerpPermission)
            else permissions
        )
        if file is None:
            return any(
                UserPolicyManager(self.user).has_global_permission(File, permission)
                for permission in requested
            )
        if requested != (BloomerpPermission.VIEW,):
            return any(
                self.has_access_to_file(file)
                if permission == BloomerpPermission.VIEW
                else self._can_mutate_file(file, permission)
                for permission in requested
            )
        if self.user.is_superuser:
            return True
        if not file.persisted:
            return self.user.is_authenticated and file.created_by_id == self.user.pk
        request = HttpRequest()
        request.user = self.user
        for reference in file.field_references.select_related(
            "application_field__content_type"
        ):
            model = reference.application_field.get_model()
            obj = (
                model._base_manager.filter(pk=reference.object_id).first()
                if model
                else None
            )
            if obj is not None:
                if model._meta.model_name == "comment":
                    parent = obj.content_object
                    if parent is not None and can_read_object_field(
                        request, parent, "comments"
                    ):
                        return True
                elif can_read_object_field(
                    request, obj, reference.application_field.field
                ):
                    return True
        if file.content_type_id and file.object_id:
            model = file.content_type.model_class()
            obj = (
                model._base_manager.filter(pk=file.object_id).first() if model else None
            )
            return obj is not None and can_read_object_field(request, obj, "files")
        if file.field_references.exists() or file.content_type_id or file.object_id:
            return False
        return UserPolicyManager(self.user).has_global_permission(
            File, BloomerpPermission.VIEW
        )

    def has_access_to_linked_object(
        self,
        linked_object: Model | None,
        operation: BloomerpPermission,
        *,
        field_name: str = "files",
    ) -> bool:
        """Check row access and the specific field owning a linked file operation."""
        if linked_object is None:
            return False

        permission_manager = UserPolicyManager(self.user)
        if not permission_manager.has_access_to_object(
            linked_object,
            BloomerpPermission.VIEW,
        ):
            return False

        return (
            permission_manager.get_accessible_fields_for_object(
                linked_object, operation
            )
            .filter(field=field_name)
            .exists()
        )

    def _can_mutate_file(
        self,
        file: File,
        operation: BloomerpPermission,
    ) -> bool:
        """Protect embedded file bytes while authorizing ordinary file mutations."""
        if file.field_references.filter(occurrence_id__isnull=False).exists():
            return False
        if self.user.is_superuser:
            return True

        linked_object = get_file_linked_object(file)
        if linked_object is not None:
            return self.has_access_to_linked_object(
                linked_object, operation, field_name=file.linked_field_name or "files"
            )

        if file.linked_content_type_id or file.linked_object_id:
            return False
        permission_manager = UserPolicyManager(self.user)
        return permission_manager.has_global_permission(File, operation)

    def has_access_to_folder(
        self,
        folder: FileFolder | None,
        permission: BloomerpPermission = BloomerpPermission.VIEW,
    ) -> bool:
        """Authorize folder operations, including discovery through accessible descendants."""
        if folder is None:
            return UserPolicyManager(self.user).has_global_permission(
                FileFolder, permission
            )
        if permission != BloomerpPermission.VIEW:
            from bloomerp.services.file_services import get_folder_linked_object

            linked_object = get_folder_linked_object(folder)
            if linked_object is not None:
                return self.has_access_to_linked_object(linked_object, permission)
            if folder.content_type_id or folder.object_id:
                return False
            return UserPolicyManager(self.user).has_global_permission(
                FileFolder, permission
            )
        if self.user.is_superuser or UserPolicyManager(self.user).has_global_permission(
            File, BloomerpPermission.VIEW
        ):
            return True

        from bloomerp.services.file_services import get_folder_linked_object

        linked_object = get_folder_linked_object(folder)
        if linked_object is not None and self.has_access_to_linked_object(
            linked_object, BloomerpPermission.VIEW
        ):
            return True

        if any(self.has_access_to_file(file) for file in folder.files.all()):
            return True

        children = FileFolder.objects.filter(parent=folder).prefetch_related("files")
        return any(self.has_access_to_folder(child) for child in children)


def get_file_linked_object(file: File) -> Model | None:
    """Resolve the canonical field owner, using the file browser's batched cache."""
    if "_linked_object" in file.__dict__:
        return file.__dict__["_linked_object"]
    reference = getattr(file, "field_reference", None)
    content_type = (
        reference.application_field.content_type
        if reference is not None
        else file.content_type
    )
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
        content_type = (
            reference.application_field.content_type
            if reference is not None
            else file.content_type
        )
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


def get_linked_object_files_field(
    linked_object: Model | None,
) -> ApplicationField | None:
    """Return the ApplicationField governing a linked object's files relation."""
    if linked_object is None:
        return None
    return ApplicationField.get_by_field(linked_object.__class__, "files")
