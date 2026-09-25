"""Store rich-text images as files linked to their model field and object."""

import base64
import binascii
import hashlib
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from bloomerp.model_fields.text_editor_field import TextEditorField
from bloomerp.models.files.file import File

IMAGE_EXTENSIONS = {
    "image/apng": "apng",
    "image/avif": "avif",
    "image/bmp": "bmp",
    "image/gif": "gif",
    "image/heic": "heic",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/svg+xml": "svg",
    "image/tiff": "tiff",
    "image/webp": "webp",
}


def _editor_fields(sender: type[models.Model]) -> list[TextEditorField]:
    """Return the text editor fields declared on a concrete model."""
    return [field for field in sender._meta.concrete_fields if isinstance(field, TextEditorField)]


def _decode_image(source: str) -> tuple[bytes, str] | None:
    """Decode a supported inline image, leaving ordinary URLs untouched."""
    if not source.startswith("data:image/"):
        return None
    header, separator, payload = source.partition(",")
    mime_type = header.removeprefix("data:").removesuffix(";base64").lower()
    if not separator or not header.endswith(";base64") or mime_type not in IMAGE_EXTENSIONS:
        raise ValidationError("Unsupported inline text editor image")
    try:
        content = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValidationError("Invalid inline text editor image") from exc
    if not content or len(content) > 20 * 1024 * 1024:
        raise ValidationError("Text editor image must be between 1 byte and 20 MB")
    return content, IMAGE_EXTENSIONS[mime_type]


def _image_url(file: File) -> str:
    """Use a URL that resolves from any editor or document-template page."""
    url = file.url
    return url if url.startswith(("/", "http://", "https://")) else f"/{url}"


def _matches_image_url(source: str, file: File) -> bool:
    """Recognize an owned image after browser URL normalization."""
    stored_url = _image_url(file)
    source_parts = urlsplit(source)
    stored_parts = urlsplit(stored_url)
    if stored_parts.netloc and source_parts.netloc != stored_parts.netloc:
        return False
    return source_parts.path == stored_parts.path


def _sync_field_images(instance: models.Model, field: TextEditorField) -> None:
    """Replace inline images and remove files absent from the saved field HTML."""
    value = getattr(instance, field.attname)
    content_type = ContentType.objects.get_for_model(instance)
    linked_files = list(File.objects.filter(
        content_type=content_type,
        object_id=str(instance.pk),
        meta__text_editor_field=field.name,
    ))
    if not value and not linked_files:
        return

    document = BeautifulSoup(value or "", "html.parser")
    by_digest = {
        (item.meta or {}).get("text_editor_sha256"): item
        for item in linked_files
        if (item.meta or {}).get("text_editor_sha256")
    }
    referenced_ids: set[Any] = set()
    changed = False
    for image in document.find_all("img"):
        source = image.get("src", "")
        decoded = _decode_image(source)
        if decoded is not None:
            content, extension = decoded
            digest = hashlib.sha256(content).hexdigest()
            file = by_digest.get(digest)
            if file is None:
                file = File.objects.create(
                    file=ContentFile(content, name=f"text-editor-{digest}.{extension}"),
                    name=f"text-editor-{digest}.{extension}",
                    content_type=content_type,
                    object_id=str(instance.pk),
                    persisted=True,
                    meta={"text_editor_field": field.name, "text_editor_sha256": digest},
                )
                by_digest[digest] = file
            image["src"] = _image_url(file)
            source = _image_url(file)
            changed = True
        for file in linked_files:
            if _matches_image_url(source, file):
                referenced_ids.add(file.pk)
        if decoded is not None:
            referenced_ids.add(by_digest[digest].pk)

    if changed:
        normalized = str(document)
        sender = type(instance)
        sender._base_manager.filter(pk=instance.pk).update(**{field.attname: normalized})
        setattr(instance, field.attname, normalized)

    for file in linked_files:
        if file.pk not in referenced_ids:
            file.delete()


@receiver(post_save, dispatch_uid="bloomerp.sync_text_editor_images")
def sync_text_editor_images(
    sender: type[models.Model], instance: models.Model, created: bool, **kwargs: Any
) -> None:
    """Synchronize images after the owning object has an ID."""
    if sender is File:
        return
    update_fields = kwargs.get("update_fields")
    for field in _editor_fields(sender):
        if update_fields is None or field.name in update_fields or field.attname in update_fields:
            _sync_field_images(instance, field)


@receiver(post_delete, dispatch_uid="bloomerp.delete_text_editor_images")
def delete_text_editor_images(
    sender: type[models.Model], instance: models.Model, **kwargs: Any
) -> None:
    """Delete linked editor images when their owning object is deleted."""
    if sender is File or not _editor_fields(sender):
        return
    content_type = ContentType.objects.get_for_model(instance)
    for file in File.objects.filter(
        content_type=content_type,
        object_id=str(instance.pk),
        meta__text_editor_field__isnull=False,
    ):
        file.delete()
