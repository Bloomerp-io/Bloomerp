"""Directed object references with optional editor occurrence identity."""

from typing import ClassVar
from django.db import models
from bloomerp.models.definition import BloomerpModelConfig, ApiSettings


class Tag(models.Model):
    """Connect a source object to a readable target object."""

    bloomerp_config = BloomerpModelConfig(
        is_internal=True, api_settings=ApiSettings(enable_auto_generation=False)
    )
    source_content_type = models.ForeignKey(
        "contenttypes.ContentType", on_delete=models.CASCADE, related_name="source_tags"
    )
    source_object_id = models.CharField(max_length=255)
    target_content_type = models.ForeignKey(
        "contenttypes.ContentType", on_delete=models.CASCADE, related_name="target_tags"
    )
    target_object_id = models.CharField(max_length=255)
    application_field = models.ForeignKey(
        "bloomerp.ApplicationField", null=True, blank=True, on_delete=models.CASCADE
    )
    occurrence_id = models.UUIDField(null=True, blank=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["source_content_type", "source_object_id"]),
            models.Index(fields=["target_content_type", "target_object_id"]),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    models.Q(application_field__isnull=True, occurrence_id__isnull=True)
                    | models.Q(
                        application_field__isnull=False, occurrence_id__isnull=False
                    )
                ),
                name="tag_inline_pair",
            ),
            models.UniqueConstraint(
                fields=[
                    "source_content_type",
                    "source_object_id",
                    "target_content_type",
                    "target_object_id",
                ],
                condition=models.Q(application_field__isnull=True),
                name="tag_manual_unique",
            ),
            models.UniqueConstraint(
                fields=[
                    "source_content_type",
                    "source_object_id",
                    "application_field",
                    "occurrence_id",
                ],
                condition=models.Q(application_field__isnull=False),
                name="tag_occurrence_unique",
            ),
        ]
