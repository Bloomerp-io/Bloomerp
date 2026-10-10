"""Associate files with records, attachment fields, or individual editor placements."""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models, router, transaction
from django.utils.translation import gettext_lazy as _

from bloomerp.files.querysets import FileIntegrityQuerySet
from bloomerp.models import BloomerpModel
from bloomerp.models.definition import BloomerpModelConfig, StringSearchSettings
from bloomerp.modules.file_management import FileManagement

FILE_REFERENCE_CONFIG = BloomerpModelConfig(
    module=FileManagement,
    is_internal=True,
    string_search_settings=StringSearchSettings(allow_global_search=False),
)


class FileReference(BloomerpModel):
    """Track one file usage without owning or deleting the underlying stored content."""

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_file_reference"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(occurrence_id__isnull=True)
                | models.Q(application_field__isnull=False),
                name="file_ref_occurrence_has_field",
            ),
            models.CheckConstraint(
                condition=~models.Q(object_id=""), name="file_ref_object_id_not_empty"
            ),
            models.UniqueConstraint(
                fields=["file", "content_type", "object_id"],
                condition=models.Q(
                    application_field__isnull=True, occurrence_id__isnull=True
                ),
                name="file_ref_record_unique",
            ),
            models.UniqueConstraint(
                fields=["file", "content_type", "object_id", "application_field"],
                condition=models.Q(
                    application_field__isnull=False, occurrence_id__isnull=True
                ),
                name="file_ref_field_unique",
            ),
            models.UniqueConstraint(
                fields=[
                    "content_type",
                    "object_id",
                    "application_field",
                    "occurrence_id",
                ],
                condition=models.Q(occurrence_id__isnull=False),
                name="file_ref_occurrence_unique",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["content_type", "object_id", "application_field"],
                name="file_ref_record_field_idx",
            ),
            models.Index(fields=["occurrence_id"], name="file_ref_occurrence_idx"),
        ]

    bloomerp_config = FILE_REFERENCE_CONFIG
    integrity_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "id",
            "pk",
            "file",
            "file_id",
            "content_type",
            "content_type_id",
            "object_id",
            "application_field",
            "application_field_id",
            "occurrence_id",
        }
    )
    objects = FileIntegrityQuerySet.as_manager()
    avatar = None
    file = models.ForeignKey(
        "bloomerp.FileNode", on_delete=models.PROTECT, related_name="references"
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=100)
    content_object = GenericForeignKey("content_type", "object_id")
    application_field = models.ForeignKey(
        "bloomerp.ApplicationField", on_delete=models.CASCADE, null=True, blank=True
    )
    occurrence_id = models.UUIDField(null=True, blank=True)

    def clean(self) -> None:
        """Require an existing record, a file node, and a compatible field/occurrence."""
        from bloomerp.model_fields.file_field import BloomerpFileField
        from bloomerp.models.application_field import ApplicationField
        from bloomerp.models.files.file_node import FileNode

        super().clean()
        database = self._state.db or router.db_for_write(type(self), instance=self)
        if (
            not FileNode.objects.using(database)
            .filter(pk=self.file_id, kind=FileNode.FileNodeKind.FILE)
            .exists()
        ):
            raise ValidationError(
                {"file": _("References must point to an existing file node.")}
            )
        content_type = (
            ContentType.objects.db_manager(database)
            .filter(pk=self.content_type_id)
            .first()
        )
        model = content_type.model_class() if content_type else None
        try:
            target_id = model._meta.pk.to_python(self.object_id) if model else None
            exists = (
                model is not None
                and model._base_manager.using(database).filter(pk=target_id).exists()
            )
        except (ValidationError, ValueError, TypeError):
            exists = False
        if not exists:
            raise ValidationError({"object_id": _("The referenced record must exist.")})
        self.object_id = str(target_id)
        if self.application_field_id is None:
            if self.occurrence_id is not None:
                raise ValidationError(
                    {"occurrence_id": _("Editor occurrences require a field.")}
                )
            return
        application_field = (
            ApplicationField.objects.using(database)
            .filter(pk=self.application_field_id)
            .first()
        )
        if (
            application_field is None
            or application_field.content_type_id != self.content_type_id
        ):
            raise ValidationError(
                {
                    "application_field": _(
                        "The field must belong to the referenced model."
                    )
                }
            )
        try:
            field = model._meta.get_field(application_field.field)
        except FieldDoesNotExist as error:
            raise ValidationError(
                {"application_field": _("The referenced field no longer exists.")}
            ) from error
        if isinstance(field, BloomerpFileField):
            if self.occurrence_id is not None:
                raise ValidationError(
                    {
                        "occurrence_id": _(
                            "Attachment fields do not have editor occurrences."
                        )
                    }
                )
        elif isinstance(field, models.TextField):
            if self.occurrence_id is None:
                raise ValidationError(
                    {"occurrence_id": _("Editor references require an occurrence ID.")}
                )
        else:
            raise ValidationError(
                {"application_field": _("Expected an attachment or rich-text field.")}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate every association before saving without altering file placement."""
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        self._state.db = database
        with transaction.atomic(using=database):
            self.full_clean()
            super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Describe the file usage without resolving potentially private record labels."""
        return f"{self.file_id} → {self.content_type_id}:{self.object_id}"
