"""Shared validation and communication module configuration for calendar records."""

from typing import Any

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import BloomerpModelConfig


class CalendarModel(BloomerpModel):
    """Validate ordinary calendar saves without granting additional access."""

    avatar = None
    bloomerp_config = BloomerpModelConfig(module="communication")

    class Meta(BloomerpModel.Meta):
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate calendar fields and constraints before persisting a record."""
        self.full_clean()
        super().save(*args, **kwargs)
