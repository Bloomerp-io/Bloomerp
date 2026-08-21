import os
import uuid
from typing import Iterable

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import UploadedFile
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.translation import gettext_lazy as _, gettext_noop

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import BloomerpModelConfig, ObjectAction, ObjectModalAction
from bloomerp.models.mixins.string_search_model_mixin import StringSearchModelMixin
from bloomerp.models.mixins.timestamp_model_mixin import TimestampModelMixin
from bloomerp.models.mixins.user_stamp_model_mixin import UserStampModelMixin
from bloomerp.services.file_services import ensure_folder_hierarchy_for_object


def _can_view_file(request: HttpRequest, file: "File") -> bool:
    from bloomerp.services.file_permission_services import user_can_view_file

    return file.persisted and bool(file.file) and user_can_view_file(request, file)


def _view_file(request: HttpRequest, file: "File") -> HttpResponse:
    """Redirect an HTMX object action to the stored file URL."""
    if not _can_view_file(request, file):
        return HttpResponse(status=403)
    response = HttpResponse(status=204)
    response["HX-Redirect"] = file.url
    return response


def _can_manage_file(request: HttpRequest, file: "File") -> bool:
    from bloomerp.services.file_permission_services import user_can_mutate_file

    return file.persisted and user_can_mutate_file(request, file, ("change", "add"))


def _can_delete_file(request: HttpRequest, file: "File") -> bool:
    from bloomerp.services.file_permission_services import user_can_mutate_file

    return file.persisted and user_can_mutate_file(request, file, ("delete",))


class File(
    TimestampModelMixin,
    StringSearchModelMixin,
    UserStampModelMixin,
    models.Model,
):
    class Meta(BloomerpModel.Meta):
        verbose_name = _("File")
        verbose_name_plural = _("Files")
        managed = True
        db_table = "bloomerp_file"

    bloomerp_config = BloomerpModelConfig(
        string_search_fields=["name"],
        object_actions=[
            ObjectAction(
                id="view_file",
                label=gettext_noop("View"),
                execution_func=_view_file,
                should_render_func=_can_view_file,
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

    def save(self, *args, **kwargs):
        # Check if a new file is being uploaded
        if self.pk:
            try:
                old_file = File.objects.get(pk=self.pk).file
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

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Delete the file when the object is deleted
        try:
            self.file.delete()
        except FileNotFoundError:
            pass
        super().delete(*args, **kwargs)

    def auto_name(self):
        """Returns the name of the file."""
        return self.file.name

    @classmethod
    def upload_files_to_object(cls, object:models.Model, files:Iterable[UploadedFile]) -> list['File']:
        """Uploads files to a certain object
        """
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
    
        
    

    
