"""Unique label assignments to generic parent objects."""

from typing import ClassVar
from django.db import models
from bloomerp.models.definition import BloomerpModelConfig, ApiSettings


class ObjectLabel(models.Model):
    """Assign each label once to a parent independently of its fields."""

    bloomerp_config = BloomerpModelConfig(
        is_internal=True, api_settings=ApiSettings(enable_auto_generation=False)
    )
    label = models.ForeignKey("bloomerp.Label", on_delete=models.CASCADE)
    content_type = models.ForeignKey(
        "contenttypes.ContentType", on_delete=models.CASCADE
    )
    object_id = models.CharField(max_length=255)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["content_type", "object_id", "label"],
                name="object_label_unique",
            )
        ]
