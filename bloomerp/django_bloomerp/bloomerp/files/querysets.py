"""Keep bulk file writes from bypassing cross-record model validation."""

from collections.abc import Iterable
from typing import Any

from django.db import models


class FileIntegrityQuerySet(models.QuerySet):
    """Allow bulk metadata edits but require validated saves for structural changes."""

    def update(self, **kwargs: Any) -> int:
        """Reject structural updates that bypass the file models' save validation."""
        if self.model.integrity_fields.intersection(kwargs):
            raise ValueError("Use individual save() calls for file integrity fields.")
        return super().update(**kwargs)

    def bulk_create(
        self,
        objs: Iterable[models.Model],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: list[str] | None = None,
        unique_fields: list[str] | None = None,
    ) -> list[models.Model]:
        """Require individual creation so tree and reference validation always run."""
        raise ValueError(
            "Use individual save() calls to create file nodes or references."
        )

    def bulk_update(
        self,
        objs: Iterable[models.Model],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        """Permit bulk metadata edits while rejecting structural field changes."""
        fields = tuple(fields)
        if self.model.integrity_fields.intersection(fields):
            raise ValueError("Use individual save() calls for file integrity fields.")
        return super().bulk_update(objs, fields, batch_size=batch_size)
