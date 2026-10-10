"""Keep reference-owned file records and stored bytes aligned with deletion."""

from __future__ import annotations

from functools import partial
from typing import Any

from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from bloomerp.models.files.file import File
from bloomerp.models.files.file_field_reference import FileFieldReference


@receiver(post_delete, sender=File, dispatch_uid="bloomerp.delete_file_bytes")
def delete_file_bytes(sender: type[File], instance: File, **kwargs: Any) -> None:
    """Remove stored bytes for instance, queryset, and cascading file deletions."""
    from bloomerp.models.files.file_node import FileNode

    # The additive migration reuses storage keys, so legacy cleanup must keep them.
    if (
        instance.file
        and FileNode.objects.using(instance._state.db or "default")
        .filter(content=instance.file.name)
        .exists()
    ):
        return
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
    if (
        file is not None
        and instance.occurrence_id is None
        and not file.field_references.exists()
        and not file.object_id
    ):
        file.delete(using=using)


# TODO: Refactor into different file
@receiver(post_delete, dispatch_uid="bloomerp.delete_object_references")
def delete_object_references(
    sender: type[models.Model], instance: models.Model, using: str, **kwargs: Any
) -> None:
    """Clean source and target links while preserving files shared by surviving objects."""
    from django.contrib.contenttypes.models import ContentType

    from bloomerp.models import (
        BloomerpModel,
        Comment,
        FileReference,
        Mention,
        ObjectLabel,
        Tag,
    )

    if not issubclass(sender, BloomerpModel) and sender is not Comment:
        return
    content_type = ContentType.objects.db_manager(using).get_for_model(sender)
    identity = str(instance.pk)
    Mention.objects.using(using).filter(
        content_type=content_type, object_id=identity
    ).delete()
    Tag.objects.using(using).filter(
        models.Q(source_content_type=content_type, source_object_id=identity)
        | models.Q(target_content_type=content_type, target_object_id=identity)
    ).delete()
    ObjectLabel.objects.using(using).filter(
        content_type=content_type, object_id=identity
    ).delete()
    FileFieldReference.objects.using(using).filter(
        application_field__content_type=content_type, object_id=identity
    ).delete()
    FileReference.objects.using(using).filter(
        content_type=content_type, object_id=identity
    ).delete()


def remove_unused_node_bytes(storage: Any, name: str, using: str) -> None:
    """Remove committed node content only after every legacy or new storage owner is gone."""
    from bloomerp.models.files.file_node import FileNode

    if (
        File.objects.using(using).filter(file=name).exists()
        or FileNode.objects.using(using).filter(content=name).exists()
    ):
        return
    try:
        storage.delete(name)
    except FileNotFoundError:
        pass


@receiver(
    post_delete,
    sender="bloomerp.FileNode",
    dispatch_uid="bloomerp.delete_file_node_bytes",
)
def delete_file_node_bytes(
    sender: type[models.Model], instance: models.Model, using: str, **kwargs: Any
) -> None:
    """Defer byte deletion until commit so rolled-back deletions retain their content."""
    if instance.content:
        transaction.on_commit(
            partial(
                remove_unused_node_bytes,
                instance.content.storage,
                instance.content.name,
                using,
            ),
            using=using,
        )
