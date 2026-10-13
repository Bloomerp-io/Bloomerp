"""Keep reference-owned file records and stored bytes aligned with deletion."""

from __future__ import annotations

from functools import partial
from typing import Any

from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

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
    FileReference.objects.using(using).filter(
        content_type=content_type, object_id=identity
    ).delete()


def remove_unused_node_bytes(storage: Any, name: str, using: str) -> None:
    """Remove committed content only after every file node sharing its key is gone."""
    from bloomerp.models.files.file_node import FileNode

    if FileNode.objects.using(using).filter(content=name).exists():
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
