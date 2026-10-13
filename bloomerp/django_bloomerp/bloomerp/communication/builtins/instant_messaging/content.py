"""Sanitize editor HTML and translate it at provider transport boundaries."""

from uuid import UUID

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import HttpRequest

from bloomerp.models.communication.instant_messaging import IMConversation
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.services.object_reference_services import (
    Reference,
    object_reference_metadata,
    validate_reference,
)

from bloomerp.utils.rich_text import format_content, sanitize_html


def prepare_content(
    content: str, user: AbstractBloomerpUser, conversation: IMConversation
) -> tuple[str, str]:
    """Validate tagged targets and return sanitized HTML followed by plain text."""
    if len(content) > 100_000:
        raise ValidationError("Message is too long.")
    original = BeautifulSoup(content, "html.parser")
    if original.find(["img", "video", "audio"]):
        raise ValidationError("Images and media are not supported in messages yet.")
    soup = BeautifulSoup(sanitize_html(content), "html.parser")
    request = HttpRequest()
    request.user = user
    seen: set[UUID] = set()
    for node in soup.select("[data-reference-kind]"):
        try:
            kind = str(node["data-reference-kind"])
            if kind not in ("user", "object"):
                raise ValueError
            occurrence = UUID(str(node["data-occurrence-id"]))
            if occurrence in seen:
                raise ValueError
            seen.add(occurrence)
            target_id = str(node["data-target-id"])
            content_type_id = (
                int(node["data-target-content-type-id"]) if kind == "object" else None
            )
            reference = Reference(kind, target_id, content_type_id, occurrence)
            validate_reference(request, reference, conversation)
            model = (
                get_user_model()
                if kind == "user"
                else ContentType.objects.get(pk=content_type_id).model_class()
            )
            target = model._base_manager.get(pk=target_id)
            node.string = str(target)
        except (ValueError, TypeError, KeyError) as error:
            raise ValidationError("Invalid object reference.") from error
    html = str(soup)
    plain = format_content(html, "plain")
    if not plain.replace("\u200b", "").strip():
        raise ValidationError("Write a message before sending.")
    if len(plain) > 20_000:
        raise ValidationError("Message is too long.")
    return html, plain


def render_message_html(
    content: str, user: AbstractBloomerpUser, conversation: IMConversation
) -> str:
    """Resolve object-tag links for the reader without trusting serialized URLs."""
    soup = BeautifulSoup(sanitize_html(content), "html.parser")
    request = HttpRequest()
    request.user = user
    for node in soup.select('[data-reference-kind="object"]'):
        try:
            content_type_id = int(node["data-target-content-type-id"])
            target_id = str(node["data-target-id"])
            validate_reference(
                request, Reference("object", target_id, content_type_id), conversation
            )
            model = ContentType.objects.get(pk=content_type_id).model_class()
            target = model._base_manager.get(pk=target_id)
            url = object_reference_metadata(target).get("url")
            if url:
                node["data-reference-url"] = url
        except (ValidationError, ObjectDoesNotExist, ValueError, TypeError, KeyError):
            # Keep the message's label, but do not offer a preview of an unreadable target.
            node.attrs = {"class": "text-primary font-medium"}
    return str(soup)
