"""User references owned by an object, optionally identifying an editor occurrence."""

from typing import ClassVar
from django.conf import settings
from django.db import models
from bloomerp.models.definition import BloomerpModelConfig, ApiSettings


class Mention(models.Model):
    """Store manual mentions and independently removable inline occurrences."""

    bloomerp_config = BloomerpModelConfig(
        is_internal=True, api_settings=ApiSettings(enable_auto_generation=False)
    )
    content_type = models.ForeignKey(
        "contenttypes.ContentType", on_delete=models.CASCADE
    )
    object_id = models.CharField(max_length=255)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    application_field = models.ForeignKey(
        "bloomerp.ApplicationField", null=True, blank=True, on_delete=models.CASCADE
    )
    occurrence_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "bloomerp_mention"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["content_type", "object_id"])
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    models.Q(application_field__isnull=True, occurrence_id__isnull=True)
                    | models.Q(
                        application_field__isnull=False, occurrence_id__isnull=False
                    )
                ),
                name="mention_inline_pair",
            ),
            models.UniqueConstraint(
                fields=["content_type", "object_id", "user"],
                condition=models.Q(application_field__isnull=True),
                name="mention_manual_unique",
            ),
            models.UniqueConstraint(
                fields=[
                    "content_type",
                    "object_id",
                    "application_field",
                    "occurrence_id",
                ],
                condition=models.Q(application_field__isnull=False),
                name="mention_occurrence_unique",
            ),
        ]
