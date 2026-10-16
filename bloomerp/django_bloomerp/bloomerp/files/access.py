"""Authorize file bytes through current generic or field-specific references."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, Model, OuterRef, Q, QuerySet, Subquery, Value
from django.db.models.functions import Cast, Replace
from django.http import HttpRequest

from bloomerp.models import ApplicationField
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
        """Check one persisted file using the same read scope as file collections."""
        from bloomerp.models.files.file_node import FileNode

        return self.get_queryset(FileNode.objects.filter(pk=file.pk)).exists()

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

    def get_queryset(
        self,
        queryset: QuerySet[FileNode],
        related_object: Model | None = None,
    ) -> QuerySet[FileNode]:
        """Filter readable file nodes in SQL, compiling grants once per target model.

        Referenced files require one readable owner field. Unreferenced uploads
        require their uploader or global library access. This scope is read-only;
        mutations still require permission on every affected reference.
        """
        from bloomerp.models import Comment, FileReference

        files = queryset.filter(kind="FILE", content__isnull=False).exclude(content="")
        files = files.filter(
            Q(meta__bulk_upload__isnull=True)
            | Q(meta__bulk_upload=None)
            | Q(meta__bulk_upload={})
        )
        if related_object is not None:
            files = files.filter(
                references__content_type=ContentType.objects.get_for_model(related_object),
                references__object_id=str(related_object.pk),
            ).distinct()
        if self.user.is_superuser:
            return files

        references = FileReference.objects.filter(file_id__in=files.values("pk"))
        references = references.annotate(
            _file_owner_uuid=Replace("object_id", Value("-"), Value(""))
        )
        content_types = list(ContentType.objects.filter(
            pk__in=references.values("content_type_id")
        ))
        comment_type = ContentType.objects.get_for_model(Comment)
        comments = Comment._base_manager.annotate(
            _file_comment_id=Cast("pk", output_field=models.CharField()),
            _file_owner_uuid=Replace("object_id", Value("-"), Value("")),
        ).filter(
            _file_comment_id__in=references.filter(
                content_type=comment_type, application_field__isnull=False
            ).values("object_id")
        )
        if any(ct.pk == comment_type.pk for ct in content_types):
            parent_types = ContentType.objects.filter(pk__in=comments.values("content_type_id"))
            content_types = list({ct.pk: ct for ct in [*content_types, *parent_types]}.values())

        request = HttpRequest()
        request.user = self.user
        resolver = ApiAccessResolver(request)
        readable_references = Q(pk__in=[])
        for content_type in content_types:
            model = content_type.model_class()
            if model is None:
                continue
            compilation = DjangoQPermissionCompiler(
                resolver.get_applicable_access_rules(model, "retrieve"),
                user=self.user,
                model=model,
            ).compile("view")
            for row_filter, fields in compilation.field_filters.items():
                owners = model._base_manager.filter(compilation.row_filter).filter(row_filter)
                owner_filter = reference_owner_filter(model, owners)
                field_ids = [field.pk for field in fields]
                field_names = {field.field for field in fields}
                field_filter = Q(application_field_id__in=field_ids)
                if "files" in field_names:
                    field_filter |= Q(application_field__isnull=True)
                if model is Comment:
                    # Field attachments on comments follow the parent's comments field.
                    field_filter &= Q(application_field__isnull=True)
                readable_references |= Q(content_type=content_type) & field_filter & owner_filter
                if "comments" in field_names:
                    readable_comments = comments.filter(content_type=content_type).filter(owner_filter)
                    readable_references |= (
                        Q(content_type=comment_type, application_field__isnull=False)
                        & reference_owner_filter(Comment, readable_comments)
                    )

        readable = Q(pk__in=references.filter(readable_references).values("file_id"))
        if self.user.is_authenticated:
            unreferenced = ~Exists(FileReference.objects.filter(file_id=OuterRef("pk")))
            permission_manager = resolver.permission_manager
            library_manager = (
                UserPolicyManager(self.user, use_request_token=False)
                if permission_manager.token is not None else permission_manager
            )
            if library_manager.has_global_permission(queryset.model, BloomerpPermission.VIEW):
                readable |= Q(unreferenced)
            else:
                readable |= Q(unreferenced) & Q(created_by_id=self.user.pk)
                if resolver.permission_manager.has_global_permission(queryset.model, BloomerpPermission.VIEW):
                    scoped_files = resolver.permission_manager.get_accessible_queryset(
                        queryset.model, BloomerpPermission.VIEW,
                    )
                    readable |= Q(unreferenced) & Q(pk__in=scoped_files.values("pk"))
        return files.filter(readable)


def reference_owner_filter(model: type[Model], owners: QuerySet[Model]) -> Q:
    """Compare generic reference IDs to owner keys in SQL across integer and UUID models."""
    owner_ids = owners.order_by().annotate(
        _file_owner_pk=Cast("pk", output_field=models.CharField())
    )
    if isinstance(model._meta.pk, models.UUIDField):
        # SQLite stores UUIDs without hyphens; PostgreSQL casts include them.
        owner_ids = owner_ids.annotate(
            _file_owner_pk=Replace("_file_owner_pk", Value("-"), Value(""))
        )
        return Q(_file_owner_uuid__in=Subquery(owner_ids.values("_file_owner_pk")))
    return Q(object_id__in=Subquery(owner_ids.values("_file_owner_pk")))
