"""Keep reference-owned file records and stored bytes aligned with deletion."""

from __future__ import annotations

from typing import Any

from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver

from bloomerp.models.files.file import File
from bloomerp.models.files.file_field_reference import FileFieldReference


@receiver(post_delete, sender=File, dispatch_uid="bloomerp.delete_file_bytes")
def delete_file_bytes(sender: type[File], instance: File, **kwargs: Any) -> None:
    """Remove stored bytes for instance, queryset, and cascading file deletions."""
    if instance.file:
        try:
            instance.file.delete(save=False)
        except FileNotFoundError:
            pass


@receiver(
    post_delete,
    sender=FileFieldReference,
    dispatch_uid="bloomerp.delete_reference_file",
)
def delete_reference_file(
    sender: type[FileFieldReference],
    instance: FileFieldReference,
    using: str,
    origin: models.Model | models.QuerySet | None = None,
    **kwargs: Any,
) -> None:
    """Delete owned file records when references or application fields are discarded."""
    if (
        isinstance(origin, File)
        or isinstance(origin, models.QuerySet)
        and origin.model is File
        or isinstance(origin, FileFieldReference)
        and getattr(origin, "_preserve_file", False)
    ):
        return
    file = File.objects.using(using).filter(pk=instance.file_id).first()
    if file is not None:
        file.delete(using=using)
