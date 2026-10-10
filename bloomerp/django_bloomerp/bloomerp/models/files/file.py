from bloomerp.permissions.definition import BloomerpPermission
import os
import uuid
from typing import TYPE_CHECKING, Any, Iterable
from urllib.parse import quote
from uuid import UUID

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import models, transaction
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic import ValidationError as PydanticValidationError

from bloomerp.dataviews.file_browser.config import FileBrowserDataview
from bloomerp.components.files.items.preview import preview_file
from bloomerp.models import BloomerpModel
from bloomerp.models.definition import (
    BloomerpModelConfig,
    DataviewHTMLAction,
    DataviewModalAction,
    ModelViewSettings,
    ObjectAction,
    ObjectHTMLAction,
    ObjectModalAction,
    StringSearchSettings,
    get_default_dataview_actions,
)
from bloomerp.models.mixins.timestamp_model_mixin import TimestampModelMixin
from bloomerp.models.mixins.user_stamp_model_mixin import UserStampModelMixin
from bloomerp.services.file_services import ensure_folder_hierarchy_for_object

if TYPE_CHECKING:
    from bloomerp.models.files.file_folder import FileFolder
    from bloomerp.models.files.file_node import FileNode


class DocumentTemplateFileMetadata(BaseModel):
    """Identify the document template that generated a stored file."""

    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: str


class BulkUploadFileMetadata(BaseModel):
    """Describe a temporary bulk-import source file."""

    model_config = ConfigDict(extra="forbid")
    content_type_id: int = Field(gt=0)
    model_label: str
    original_filename: str


class FileSignatureMetadata(BaseModel):
    """Track PDF signature status, signer identity, and a signed output file."""

    model_config = ConfigDict(extra="forbid")
    signed: bool = False
    user_id: int | UUID | None = None
    signed_file_id: UUID | None = None


class FileMetadata(BaseModel):
    """Validated provenance for generated documents and bulk imports."""

    model_config = ConfigDict(extra="forbid")
    document_template: DocumentTemplateFileMetadata | None = None
    bulk_upload: BulkUploadFileMetadata | None = None
    signature: FileSignatureMetadata | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_metadata(cls, value: Any) -> Any:
        """Accept historical document-template and bulk-draft JSON without data loss."""
        if value is None:
            return {}
        if not isinstance(value, dict):
            return value
        value = value.copy()
        if "document_template_id" in value:
            value["document_template"] = {
                "id": value.pop("document_template_id"),
                "name": value.pop("document_template_name", ""),
            }
        if "document_template" in value and isinstance(value["document_template"], (str, UUID)):
            value["document_template"] = {"id": value["document_template"], "name": ""}
        if any(key in value for key in ("signed", "user", "signed_file_id")):
            value["signature"] = {
                "signed": value.pop("signed", False),
                "user_id": value.pop("user", None),
                "signed_file_id": value.pop("signed_file_id", None),
            }
        if value.pop("bulk_upload_draft", False):
            value["bulk_upload"] = {
                "content_type_id": value.pop("content_type_id", None),
                "model_label": value.pop("model_label", None),
                "original_filename": value.pop("original_filename", ""),
            }
            value.pop("upload_type", None)
        return value


def _can_view_file(request: HttpRequest, file: "FileNode") -> bool:
    """Expose persisted file previews only when the requester can read their scope."""
    from bloomerp.files.access import FileAccessManager
    
    return True


def _can_manage_file(request: HttpRequest, file: "File") -> bool:
    """Authorize management actions through the file's current owning scope."""
    from bloomerp.files.access import FileAccessManager

    return file.persisted and FileAccessManager(request.user).has_access_to_file(file, (BloomerpPermission.CHANGE, BloomerpPermission.ADD))


def _can_delete_file(request: HttpRequest, file: "File") -> bool:
    """Authorize deletion of persisted files through their owning scope."""
    from bloomerp.files.access import FileAccessManager

    return file.persisted and FileAccessManager(request.user).has_access_to_file(file, (BloomerpPermission.DELETE,))


def _create_folder_endpoint(context) -> str:
    endpoint = reverse("components_create_folder")
    return f"{endpoint}?{context.querystring}" if context.querystring else endpoint


def _can_create_folder(context) -> bool:
    from bloomerp.components.files.folders.create import can_create_folder

    return can_create_folder(context.request)



class File(
    TimestampModelMixin,
    UserStampModelMixin,
    models.Model,
):
    class Meta(BloomerpModel.Meta):
        verbose_name = _("File")
        verbose_name_plural = _("Files")
        managed = True
        db_table = "bloomerp_file"

    bloomerp_config = BloomerpModelConfig(
        string_search_settings=StringSearchSettings(
            string_search_fields=["name"],
        ),
        model_view_settings=ModelViewSettings(
            dataview_actions=[
                DataviewModalAction(
                    id="create_folder",
                    label="Create Folder",
                    endpoint=_create_folder_endpoint,
                    should_render_func=_can_create_folder,
                    modal_title="Create folder",
                    icon="fa fa-folder-plus"
                ),
                DataviewHTMLAction(
                    id="upload",
                    template_name="components/objects/dataview_actions/upload_files.html",
                    shortcut="mod+2",
                ),
                *get_default_dataview_actions(skip=["add"])
            ],
            default_dataviews=[
                FileBrowserDataview()
            ]

        ),
        object_actions=[
            ObjectAction(
                id="view_file",
                label=gettext_noop("View"),
                should_render_func=_can_view_file,
                execution_func=preview_file,
                target="#bloomerp-general-use-drawer-body",
                button_attrs={"bloomerp-open-drawer": "bloomerp-general-use-drawer"},
            ),
            ObjectModalAction(
                id="rename_file",
                label=gettext_noop("Rename"),
                endpoint=lambda file: reverse(
                    "components_files_rename",
                    kwargs={"file_id": file.pk},
                ),
                should_render_func=_can_manage_file,
                modal_title=gettext_noop("Rename file"),
            ),
            ObjectModalAction(
                id="move_file",
                label=gettext_noop("Move"),
                endpoint=lambda file: reverse(
                    "components_files_move",
                    kwargs={"file_id": file.pk},
                ),
                should_render_func=_can_manage_file,
                modal_title=gettext_noop("Move file"),
            ),
            ObjectModalAction(
                id="delete_file",
                label=gettext_noop("Delete"),
                endpoint=lambda file: reverse(
                    "components_files_delete",
                    kwargs={"file_id": file.pk},
                ),
                should_render_func=_can_delete_file,
                modal_title=gettext_noop("Delete file"),
            ),
        ],
    )

    def upload_to(self, filename: str) -> str:
        """Return the upload path for the file."""
        # TODO: Can fetch this from settings in the future
        root = "bloomerp"

        if self.content_type is None:
            # Default folder for files with no content type
            folder = "others"
        else:
            # Use the content type's app_label for organization
            folder = self.content_type.app_label

        # Ensure unique file names
        unique_filename = f"{uuid.uuid4()}_{filename}"

        # Return the full path
        return f"{root}/{folder}/{unique_filename}"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID"),
    )
    file = models.FileField(
        upload_to=upload_to,
        verbose_name=_("File"),
    )
    name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name=_("Name"),
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Content Type"),
    )
    object_id = models.CharField(
        max_length=36,
        null=True,
        blank=True,
        verbose_name=_("Object ID"),
    )  # In order to support both UUID and integer primary keys
    content_object = GenericForeignKey(
        "content_type",
        "object_id",
    )
    folder: "FileFolder" = models.ForeignKey(
        "bloomerp.FileFolder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="files",
        verbose_name=_("Folder"),
    )
    persisted = models.BooleanField(
        default=False,
        verbose_name=_("Persisted"),
    )  # A field to indicate if the file is temporary or persisted

    # Created/updated utils
    meta = models.JSONField(blank=True, null=True, verbose_name=_("Meta"))

    @property
    def metadata(self) -> FileMetadata:
        """Expose validated metadata rather than untyped JSON."""
        return FileMetadata.model_validate(self.meta)

    @property
    def field_reference(self) -> models.Model:
        """Expose the first reference for legacy file-browser placement callers."""
        from django.core.exceptions import ObjectDoesNotExist

        references = list(self.field_references.all())
        if not references:
            class MissingReference(ObjectDoesNotExist, AttributeError):
                """Preserve reverse-relation missing-value behavior for legacy callers."""

            raise MissingReference("This file has no field reference.")
        return next((reference for reference in references if reference.occurrence_id is None), references[0])

    @property
    def linked_object(self) -> models.Model | None:
        """Return the reference owner or the generic object associated with this file."""
        from bloomerp.files.access import get_file_linked_object

        return get_file_linked_object(self)

    @property
    def linked_field_name(self) -> str:
        """Resolve the owning field from the canonical reference rather than metadata."""
        reference = getattr(self, "field_reference", None)
        return reference.application_field.field if reference is not None else ""

    @property
    def linked_object_id(self) -> str | None:
        """Return the parent identifier for reference-backed and generic files."""
        reference = getattr(self, "field_reference", None)
        return reference.object_id if reference is not None else self.object_id

    @property
    def linked_content_type_id(self) -> int | None:
        """Return the parent model identifier for file-browser object previews."""
        reference = getattr(self, "field_reference", None)
        return reference.application_field.content_type_id if reference is not None else self.content_type_id

    @property
    def linked_object_url(self) -> str:
        """Link to the owning object's detail view and attachment field."""
        linked_object = self.linked_object
        if linked_object is None or not hasattr(linked_object, "get_absolute_url"):
            return ""
        url = linked_object.get_absolute_url()
        return f"{url}#{quote(self.linked_field_name)}" if self.linked_field_name else url

    @property
    def linked_field_label(self) -> str:
        """Return the canonical application field's human-readable label."""
        reference = getattr(self, "field_reference", None)
        return str(reference.application_field.title) if reference is not None else ""

    @property
    def url(self):
        return self.file.url

    @property
    def file_extension(self):
        """Returns the file extension of the file."""
        _, extension = os.path.splitext(self.file.name)
        return extension[1:]

    @property
    def size(self):
        """Returns the file size of the file."""
        try:
            return self.file.size
        except FileNotFoundError:
            return 0

    @property
    def size_str(self):
        """Returns the file size of the file in human readable format."""
        size = self.size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.2f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / 1024 / 1024:.2f} MB"
        else:
            return f"{size / 1024 / 1024 / 1024:.2f} GB"

    @property
    def icon_class(self):
        match self.file_extension:
            case "pdf":
                return "fa-file-pdf"

            case _:
                return "fa-file"

    def __str__(self):
        return str(self.name)

    def _ensure_auto_folder_hierarchy(self):
        if not self.content_type_id or not self.object_id:
            return None

        linked_object = self.content_object
        if linked_object is None:
            model = self.content_type.model_class()
            if model is None:
                return None
            linked_object = model.objects.filter(pk=self.object_id).first()
            if linked_object is None:
                return None

        return ensure_folder_hierarchy_for_object(
            linked_object,
            created_by=self.created_by,
            updated_by=self.updated_by,
        )

    def validate_metadata(self) -> None:
        """Normalize valid provenance to JSON and expose schema errors as Django errors."""
        try:
            self.meta = FileMetadata.model_validate(self.meta).model_dump(
                mode="json", exclude_none=True
            )
        except PydanticValidationError as error:
            raise ValidationError({"meta": str(error)}) from error

    def clean_fields(self, exclude: set[str] | None = None) -> None:
        """Validate typed provenance before Django validates the JSON column."""
        if not exclude or "meta" not in exclude:
            self.validate_metadata()
        super().clean_fields(exclude=exclude)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate metadata and save the file in its owning object's folder."""
        self.validate_metadata()
        # Check if a new file is being uploaded
        if self.pk:
            try:
                previous = File.objects.get(pk=self.pk)
                old_file = previous.file
                # If the file field is changed, delete the old file
                if old_file and old_file != self.file:
                    old_file.delete(save=False)
            except File.DoesNotExist:
                pass  # No old file exists

        # Set the name if not already set
        if not self.name:
            self.name = self.auto_name()

        if self.folder_id is None and self.content_type_id and self.object_id:
            self.folder = self._ensure_auto_folder_hierarchy()

        with transaction.atomic(using=kwargs.get("using") or self._state.db):
            super().save(*args, **kwargs)
            if self.content_type_id and self.object_id:
                self.detach_from_field()

    def detach_from_field(self) -> None:
        """Remove dedicated field ownership while preserving embedded file usages."""
        from bloomerp.models.files.file_field_reference import FileFieldReference

        reference = FileFieldReference.objects.using(self._state.db).filter(file_id=self.pk, occurrence_id__isnull=True).first()
        if reference is not None:
            reference.delete(preserve_file=True)
        self._state.fields_cache.pop("field_reference", None)
        self.__dict__.pop("_linked_object", None)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Delete the file and cascade its canonical field reference."""
        return super().delete(*args, **kwargs)

    def auto_name(self):
        """Returns the name of the file."""
        return self.file.name

    @classmethod
    def upload_files_to_object(cls, object:models.Model, files:Iterable[UploadedFile]) -> list['File']:
        """Uploads files to a certain object
        """
        from bloomerp.services.file_services import ensure_folder_hierarchy_for_object
        files = [uploaded for uploaded in files if uploaded]
        if not files:
            return []

        content_type = ContentType.objects.get_for_model(object.__class__)
        created_files: list[File] = []
        for uploaded in files:
            created_files.append(
                File.objects.create(
                    file=uploaded,
                    name=uploaded.name,
                    persisted=True,
                    content_type=content_type,
                    object_id=str(object.pk),
                )
            )

        ensure_folder_hierarchy_for_object(object)

        return created_files

    @classmethod
    def move_files_to_object(cls, target:models.Model, files:Iterable['File']) -> list['File']:
        """Moves files from one object to another

        Args:
            target (models.Model): the object to move the files to
            files (Iterable[&#39;File&#39;]): the file objects to be moved
            
        Returns:
            list of moved files
        """
        content_type = ContentType.objects.get_for_model(target.__class__)
        moved_files: list[File] = []
        for file in files:
            file.content_type = content_type
            file.object_id = str(target.pk)
            file.folder = None
            file.persisted = True
            file.save()
            moved_files.append(file)
        return moved_files
