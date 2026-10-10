"""Shared labels with normalized names and creator-managed editing."""

from typing import Any, ClassVar
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower, Trim
from bloomerp.models.definition import BloomerpModelConfig, ApiSettings
from bloomerp.models.mixins.user_stamp_model_mixin import UserStampModelMixin


class Label(UserStampModelMixin, models.Model):
    """Provide one shared, case-insensitive catalogue of labels."""

    bloomerp_config = BloomerpModelConfig(
        is_internal=True, api_settings=ApiSettings(enable_auto_generation=False)
    )
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7, default="#64748b")

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(Lower(Trim("name")), name="label_name_unique")
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Normalize label names before enforcing database uniqueness."""
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError("A label name is required.")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return the label's human-readable name."""
        return self.name
