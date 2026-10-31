"""Store immutable file content independently of its business-record references."""

from __future__ import annotations

import json
import mimetypes
from pathlib import PurePath
from typing import Any, ClassVar
from urllib.parse import urlencode

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import connections, models, router, transaction
from django.db.models import Model, QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop
from pydantic import ValidationError as PydanticValidationError

from bloomerp.components.files.items.preview import preview_file
from bloomerp.dataviews.file_browser.config import FileBrowserDataview
from bloomerp.files.definition import FileNodeMetaData
from bloomerp.files.querysets import FileIntegrityQuerySet
from bloomerp.models import BloomerpModel
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import (
    BloomerpModelConfig,
    ModelViewSettings,
    ObjectAction,
    ObjectModalAction,
    StringSearchSettings,
    get_default_dataview_actions,
)
from bloomerp.models.files.file_reference import FileReference
from bloomerp.modules.file_management import FileManagement


def _can_view_file_node(request: HttpRequest, file: FileNode) -> bool:
    """Show the preview action only for readable file nodes with content."""
    from bloomerp.files.access import FileAccessManager

    return FileAccessManager(request.user).can_read_file_node(file)


def _can_change_file_node(request: HttpRequest, file: FileNode) -> bool:
    """Show node-wide rename and move actions only when every usage permits changes."""
    from bloomerp.files.access import FileAccessManager

    return file.kind == "FILE" and FileAccessManager(request.user).can_mutate_file_node(
        file
    )


def _can_delete_file_node(request: HttpRequest, file: FileNode) -> bool:
    """Offer deletion only for unused files whose bytes the requester may remove."""
    from bloomerp.files.access import FileAccessManager
    from bloomerp.permissions.definition import BloomerpPermission

    return (
        file.kind == "FILE"
        and not file.references.exists()
        and not file.ai_artifacts.exists()
        and FileAccessManager(request.user).can_mutate_file_node(
            file, BloomerpPermission.DELETE
        )
    )


def _rename_url(file: FileNode) -> str:
    """Resolve the node rename modal."""
    return reverse("components_files_rename", kwargs={"file_id": file.pk})


def _move_url(file: FileNode) -> str:
    """Resolve the node physical-placement modal."""
    return reverse("components_files_move", kwargs={"file_id": file.pk})


def _delete_url(file: FileNode) -> str:
    """Resolve the unused node deletion modal."""
    return reverse("components_files_delete", kwargs={"file_id": file.pk})


def _email_url(file: FileNode) -> str:
    """Open the shared email composer with this file preselected as an attachment."""
    selection = {"manual": [{"kind": "file", "target_id": str(file.pk)}], "fields": {}}
    return f"{reverse('components_new_email')}?{urlencode({'object_references': json.dumps(selection)})}"


def _prepare_sign_url(file: FileNode) -> str:
    """Open the reusable signing wizard for this immutable PDF."""
    return reverse("components_document_signing_wizard", kwargs={"file_id": file.pk})


def _can_prepare_sign(request: HttpRequest, file: FileNode) -> bool:
    """Offer the signing wizard for readable PDFs when request creation is allowed."""
    from bloomerp.document_signing.access import can_create_request
    from bloomerp.permissions.manager import UserPolicyManager

    return (
        file.kind == "FILE"
        and file.metadata.extension == "pdf"
        and _can_view_file_node(request, file)
        and can_create_request(UserPolicyManager(request.user))
    )


FILE_NODE_CONFIG = BloomerpModelConfig(
    module=FileManagement,
    model_view_settings=ModelViewSettings(
        default_dataviews=[FileBrowserDataview()],
        dataview_actions=get_default_dataview_actions(skip=["add"]),
    ),
    string_search_settings=StringSearchSettings(string_search_fields=["name"]),
    object_actions=[
        ObjectAction(
            id="view_file",
            label=gettext_noop("View"),
            should_render_func=_can_view_file_node,
            execution_func=preview_file,
            target="#bloomerp-general-use-drawer-body",
            button_attrs={"bloomerp-open-drawer": "bloomerp-general-use-drawer"},
        ),
        ObjectModalAction(
            id="email",
            label=gettext_noop("Email"),
            endpoint=_email_url,
            should_render_func=_can_view_file_node,
            modal_size="full",
            modal_title=gettext_noop("New email"),
        ),
        ObjectModalAction(
            id="rename_file",
            label=gettext_noop("Rename"),
            endpoint=_rename_url,
            should_render_func=_can_change_file_node,
            modal_title=gettext_noop("Rename file"),
        ),
        ObjectModalAction(
            id="move_file",
            label=gettext_noop("Move"),
            endpoint=_move_url,
            should_render_func=_can_change_file_node,
            modal_title=gettext_noop("Move file"),
        ),
        ObjectModalAction(
            id="delete_file",
            label=gettext_noop("Delete"),
            endpoint=_delete_url,
            should_render_func=_can_delete_file_node,
            modal_title=gettext_noop("Delete file"),
        ),
        ObjectModalAction(
            id="sign",
            label=gettext_noop("Sign"),
            endpoint=_prepare_sign_url,
            should_render_func=_can_prepare_sign,
            modal_size="full",
            modal_title=gettext_noop("Sign document"),
        ),
    ],
)


def file_node_upload_to(instance: FileNode, filename: str) -> str:
    """Give new content a UUID-based key independent of names and folder moves."""
    return f"bloomerp/files/{instance.pk}{PurePath(filename).suffix.lower()}"


class FileNode(BloomerpModel):
    """Represent one physical folder or one immutable stored file."""

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_file_node"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    models.Q(kind="FILE", content__isnull=False) & ~models.Q(content="")
                    | models.Q(kind="FOLDER")
                    & (models.Q(content__isnull=True) | models.Q(content=""))
                ),
                name="file_node_kind_content_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(parent=models.F("pk")),
                name="file_node_not_own_parent",
            ),
        ]

    class FileNodeKind(models.TextChoices):
        FILE = "FILE", _("File")
        FOLDER = "FOLDER", _("Folder")

    bloomerp_config = FILE_NODE_CONFIG
    integrity_fields: ClassVar[frozenset[str]] = frozenset(
        {"id", "pk", "kind", "content", "parent", "parent_id"}
    )
    objects = FileIntegrityQuerySet.as_manager()
    avatar = None
    name = models.CharField(max_length=255)
    kind = models.CharField(choices=FileNodeKind.choices, max_length=9)
    content = models.FileField(
        null=True, blank=True, upload_to=file_node_upload_to, max_length=255
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    meta = models.JSONField(default=dict, blank=True)

    def clean(self) -> None:
        """Validate node shape, immutable content, and an acyclic folder-only ancestry."""
        super().clean()
        database = self._state.db or router.db_for_write(type(self), instance=self)
        nodes = type(self)._base_manager.using(database)
        if self.kind == self.FileNodeKind.FILE and not self.content:
            raise ValidationError({"content": _("A file node requires content.")})
        if self.kind == self.FileNodeKind.FOLDER and self.content:
            raise ValidationError(
                {"content": _("A folder cannot contain file content.")}
            )
        previous = nodes.filter(pk=self.pk).values("kind", "content").first()
        if previous is not None:
            if previous["kind"] != self.kind:
                raise ValidationError({"kind": _("A node's kind cannot be changed.")})
            if (previous["content"] or "") != (self.content.name or "") or (
                self.content and not self.content._committed
            ):
                raise ValidationError(
                    {"content": _("File content is immutable; create a new file node.")}
                )
        seen = {self.pk}
        parent_id = self.parent_id
        while parent_id is not None:
            if parent_id in seen:
                raise ValidationError({"parent": _("Folder cycles are not allowed.")})
            seen.add(parent_id)
            parent = nodes.filter(pk=parent_id).values("kind", "parent_id").first()
            if parent is None or parent["kind"] != self.FileNodeKind.FOLDER:
                raise ValidationError(
                    {"parent": _("The parent must be an existing folder.")}
                )
            parent_id = parent["parent_id"]

    @property
    def metadata(self) -> FileNodeMetaData:
        """Read the typed metadata snapshot without consulting file storage."""
        return FileNodeMetaData.model_validate(self.meta)

    def populate_metadata(self) -> None:
        """Capture upload facts once and reuse cached facts for immutable content."""
        try:
            metadata = self.metadata
            if self.kind == self.FileNodeKind.FOLDER:
                self.meta = FileNodeMetaData(**(metadata.model_extra or {})).model_dump(
                    mode="json", exclude_none=True
                )
                return
            fresh_upload = not self.content._committed
            filename = (
                PurePath(self.content.name).name
                if fresh_upload or not metadata.original_filename
                else metadata.original_filename
            )
            size = metadata.size
            if fresh_upload or size is None:
                try:
                    # Unsaved uploads supply their own size; legacy keys need one stat.
                    size = self.content.size
                except FileNotFoundError:
                    # Preserve missing legacy keys without misreporting zero-byte files.
                    size = None
            mime_type, encoding = mimetypes.guess_type(filename)
            self.meta = FileNodeMetaData.model_validate(
                {
                    **metadata.model_dump(),
                    "size": size,
                    "original_filename": filename,
                    "extension": PurePath(filename).suffix.lstrip(".").lower(),
                    "mime_type": mime_type or "application/octet-stream",
                    "content_encoding": encoding,
                }
            ).model_dump(mode="json", exclude_none=True)
        except PydanticValidationError as error:
            raise ValidationError({"meta": str(error)}) from error

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate node writes and persist cached content facts alongside the node."""
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            if not update_fields:
                return
            kwargs["update_fields"] = update_fields | {"meta"}
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        self._state.db = database
        with transaction.atomic(using=database):
            if (
                self.kind == self.FileNodeKind.FOLDER
                and connections[database].vendor == "postgresql"
            ):
                # One transaction lock prevents concurrent opposing moves forming a cycle.
                with connections[database].cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [18420, 1])
            if not self.name and self.content:
                self.name = PurePath(self.content.name).name
            self.full_clean()
            self.populate_metadata()
            super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Display the user-facing file or folder name."""
        return self.name

    def get_references(self, models: list[type[Model]] | None = None) -> QuerySet[FileReference]:
        """Return file usages, optionally limited to model types; callers enforce target access."""
        references = self.references.all()
        if models is not None:
            content_types = ContentType.objects.get_for_models(*models)
            references = references.filter(
                content_type_id__in=[item.pk for item in content_types.values()]
            )
        return references

    def create_reference(
        self, object: Model, field: ApplicationField | None = None
    ) -> FileReference:
        """Link a saved record or attachment field, reusing an existing reference.

        Callers authorize the target; FileReference validates the association.
        """
        if (
            self._state.adding
            or self.pk is None
            or object._state.adding
            or object.pk is None
        ):
            raise ValidationError(_("Save the file and referenced record first."))
        database = self._state.db or router.db_for_write(FileReference, instance=self)
        if object._state.db != database or (
            field is not None and field._state.db != database
        ):
            raise ValidationError(_("File references must use the same database."))
        reference, _created = FileReference.objects.using(database).get_or_create(
            file=self,
            content_type=ContentType.objects.db_manager(database).get_for_model(object),
            object_id=str(object.pk),
            application_field=field,
            occurrence_id=None,
        )
        return reference
