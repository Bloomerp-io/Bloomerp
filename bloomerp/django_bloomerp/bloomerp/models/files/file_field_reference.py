from __future__ import annotations

from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models

from bloomerp.models.definition import (
    ActivityLogSettings,
    ApiSettings,
    BloomerpModelConfig,
)


class FileFieldReference(models.Model):
    """Own a file on an application field and parent object in one shared table."""

    bloomerp_config = BloomerpModelConfig(
        is_internal=True,
        api_settings=ApiSettings(enable_auto_generation=False),
        activity_log_settings=ActivityLogSettings(enabled=False),
    )

    file = models.OneToOneField(
        "bloomerp.File",
        on_delete=models.CASCADE,
        related_name="field_reference",
    )
    object_id = models.CharField(max_length=36)
    application_field = models.ForeignKey(
        "bloomerp.ApplicationField",
        on_delete=models.CASCADE,
        related_name="file_field_references",
    )

    class Meta:
        db_table = "bloomerp_file_field_reference"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["application_field", "object_id"],
                name="file_ref_field_object_idx",
            )
        ]

    def clean(self) -> None:
        """Reject references to ordinary fields or nonexistent parent objects."""
        from bloomerp.model_fields.file_field import BloomerpFileField

        field = self.application_field._get_model_field()
        if not isinstance(field, BloomerpFileField):
            raise ValidationError(
                {"application_field": "Expected a Bloomerp file field."}
            )
        if (
            not self.application_field.get_model()
            ._base_manager.filter(pk=self.object_id)
            .exists()
        ):
            raise ValidationError({"object_id": "The owning object does not exist."})

    def delete(
        self, *args: Any, preserve_file: bool = False, **kwargs: Any
    ) -> tuple[int, dict[str, int]]:
        """Remove ownership, preserving the file only for explicit reassignment."""
        self._preserve_file = preserve_file
        return super().delete(*args, **kwargs)
