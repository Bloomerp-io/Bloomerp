"""Resolve authorized ordinary and inline email files without changing their references."""

from __future__ import annotations

import json
from email.utils import make_msgid
from io import BytesIO
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from bs4 import BeautifulSoup, Tag
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext as _
from PIL import Image, UnidentifiedImageError

from bloomerp.communication.builtins.emails.base_adapter import EmailAttachment

MAX_EMAIL_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_EMAIL_FILES = 200


def selected_email_file_ids(value: str) -> list[UUID]:
    """Accept bounded manual file selections, ignoring client-supplied presentation."""
    from bloomerp.services.object_reference_services import parse_manual_references

    if not value:
        return []
    try:
        if len(value) > 256_000:
            raise ValueError("Attachment selection too large")
        payload = json.loads(value)
        if not isinstance(payload, dict) or payload.get("fields") not in ({}, None):
            raise ValueError("Unexpected field attachments")
        references = parse_manual_references(json.dumps(payload.get("manual", [])))
        if any(reference.kind != "file" for reference in references):
            raise ValueError("Only file attachments are supported")
        return list(dict.fromkeys(UUID(reference.target_id) for reference in references))
    except (ValueError, TypeError, AttributeError, ValidationError) as exc:
        raise ValidationError(_("Invalid email attachment selection.")) from exc


def _inline_file_id(request: HttpRequest, image: Tag) -> UUID | None:
    """Recognize stored image identities without requesting any URL or trusting its host."""
    identifier = image.get("data-target-id") if image.get("data-reference-kind") == "file" else None
    source = str(image.get("src", "")).strip()
    try:
        url = urlsplit(source)
        local = not url.netloc or url.netloc == request.get_host()
        if not identifier and local and url.path.rstrip("/") == reverse("api_files_serve").rstrip("/"):
            values = parse_qs(url.query).get("file_id", [])
            if len(values) != 1:
                raise ValueError("Invalid stored image URL")
            identifier = values[0]
        if identifier:
            return UUID(str(identifier))
        if image.get("data-reference-kind") == "file" or url.scheme.lower() in {"data", "blob", "cid", "file"}:
            raise ValueError("Image has no stored file identity")
    except ValueError as exc:
        raise ValidationError(_("An inline image is not available. Upload it again or remove it before sending.")) from exc
    return None


def prepare_email_files(request: HttpRequest, body_html: str) -> tuple[str, list[EmailAttachment]]:
    """Authorize all selected and inline files before reading bytes and rewrite only the wire body."""
    from bloomerp.files.access import FileAccessManager
    from bloomerp.models.files.file_node import FileNode

    manual = selected_email_file_ids(request.POST.get("object_references", ""))
    document = BeautifulSoup(body_html, "html.parser") if "<img" in body_html.lower() else None
    images: dict[UUID, list[Tag]] = {}
    for image in document.find_all("img") if document is not None else []:
        identifier = _inline_file_id(request, image)
        if identifier is not None:
            images.setdefault(identifier, []).append(image)
    identifiers = list(dict.fromkeys([*manual, *images]))
    if len(identifiers) > MAX_EMAIL_FILES:
        raise ValidationError(_("Too many email attachments or inline images."))
    files = FileAccessManager(request.user).get_queryset(FileNode.objects.filter(pk__in=identifiers)) if identifiers else FileNode.objects.none()
    by_id = {file.pk: file for file in files}
    if len(by_id) != len(identifiers):
        raise ValidationError(_("An attachment or inline image is unavailable or you no longer have access. Remove it or select it again."))

    attachments: list[EmailAttachment] = []
    remaining = MAX_EMAIL_ATTACHMENT_BYTES
    for upload in request.FILES.getlist("attachments"):
        if not upload.size:
            continue
        if upload.size > remaining:
            raise ValidationError(_("Email attachments cannot exceed 20 MB in total."))
        content = upload.read(remaining + 1)
        remaining = _remaining_bytes(remaining, content)
        attachments.append(EmailAttachment(filename=upload.name, content=content, content_type=upload.content_type or "application/octet-stream"))

    for identifier in identifiers:
        file = by_id[identifier]
        metadata = file.metadata
        copies = int(identifier in manual) + int(identifier in images)
        if metadata.size is not None and metadata.size * copies > remaining:
            raise ValidationError(_("Email attachments cannot exceed 20 MB in total."))
        try:
            with file.content.open("rb") as stored:
                content = stored.read(remaining // copies + 1)
        except OSError as exc:
            raise ValidationError(_("An attachment or inline image could not be read. Remove it or select it again.")) from exc
        for _copy in range(copies):
            remaining = _remaining_bytes(remaining, content)
        filename = metadata.original_filename or file.name
        if identifier in manual:
            attachments.append(EmailAttachment(filename=filename, content=content, content_type=metadata.mime_type or "application/octet-stream"))
        if identifier in images:
            content_type = _image_content_type(content)
            content_id = make_msgid(domain="inline.bloomerp.invalid")[1:-1]
            attachments.append(EmailAttachment(filename=filename, content=content, content_type=content_type, content_id=content_id, disposition="inline"))
            for image in images[identifier]:
                image["src"] = f"cid:{content_id}"
                for attribute in list(image.attrs):
                    if attribute.startswith("data-") or attribute in {"srcset", "crossorigin"}:
                        del image[attribute]
                if "url(" in str(image.get("style", "")).lower():
                    del image["style"]
                if image.parent and image.parent.name == "picture":
                    for source in image.parent.find_all("source"):
                        source.decompose()
    return (str(document) if images else body_html), attachments


def get_email_attachments(request: HttpRequest) -> list[EmailAttachment]:
    """Retain the legacy helper for ordinary stored and multipart attachments."""
    return prepare_email_files(request, "")[1]


def _image_content_type(content: bytes) -> str:
    """Validate actual raster bytes instead of trusting an image label or MIME metadata."""
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format not in {"PNG", "JPEG", "GIF", "WEBP"}:
                raise ValueError("Unsupported image format")
            content_type = Image.MIME[image.format]
            image.verify()
            return content_type
    except (UnidentifiedImageError, OSError, ValueError, KeyError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValidationError(_("Inline email images must be valid PNG, JPEG, GIF or WebP files. Upload it again or remove it.")) from exc


def _remaining_bytes(remaining: int, content: bytes) -> int:
    """Enforce the aggregate limit against actual bytes, including duplicated MIME parts."""
    if len(content) > remaining:
        raise ValidationError(_("Email attachments cannot exceed 20 MB in total."))
    return remaining - len(content)
