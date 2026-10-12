"""Sanitize editor HTML and translate it at provider transport boundaries."""

from html import escape
from typing import Literal
from uuid import UUID

import bleach
from bleach.css_sanitizer import CSSSanitizer
from bs4 import BeautifulSoup, NavigableString, Tag
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

# TODO: Remove to a utility function which has no visibility to IM conversation...

TAGS = [
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "del",
    "code",
    "pre",
    "blockquote",
    "ul",
    "ol",
    "li",
    "a",
    "span",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "div",
    "hr",
    "sub",
    "sup",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "caption",
    "colgroup",
    "col",
]
REFERENCE_ATTRIBUTES = [
    "data-reference-kind",
    "data-target-id",
    "data-target-content-type-id",
    "data-occurrence-id",
]


EDITOR_CLASSES = frozenset(
    """
text-md mb-2 last:mb-0 text-4xl font-bold text-2xl mb-1 text-xl
list-disc list-inside pl-4 list-decimal bloomerp-text-editor-checklist
bloomerp-text-editor-checklist-item-checked bloomerp-text-editor-checklist-item-unchecked
bloomerp-text-editor-nested-list-item my-3 w-full table-fixed border-collapse
rounded-lg border border-gray-200 text-left border-b last:border-b-0 min-w-24
border-r px-1 py-1 align-top text-sm last:border-r-0 bg-gray-100 font-medium
bloomerp-text-editor-code-block text-primary underline italic line-through
""".split()
)
EDITOR_CSS = CSSSanitizer(
    allowed_css_properties=[
        "color",
        "background-color",
        "font-family",
        "font-size",
        "font-weight",
        "font-style",
        "text-decoration",
        "text-align",
        "vertical-align",
        "white-space",
        "line-height",
        "letter-spacing",
        "padding-left",
        "width",
        "height",
        "border",
        "border-color",
        "border-width",
        "border-style",
        "border-collapse",
    ]
)


def sanitize_html(content: str) -> str:
    """Preserve editor presentation and reference metadata while removing active content."""
    soup = BeautifulSoup(content, "html.parser")
    for node in soup.select("script, style, iframe, object, svg, math"):
        node.decompose()
    for node in soup.find_all(class_=True):
        classes = [name for name in node.get("class", []) if name in EDITOR_CLASSES]
        if classes:
            node["class"] = classes
        else:
            del node["class"]
    return bleach.clean(
        str(soup),
        tags=TAGS,
        attributes={
            "*": ["class", "style", "dir"],
            "a": ["href", "title"],
            "span": REFERENCE_ATTRIBUTES,
            "pre": ["data-text-editor-code-block"],
            "ul": ["__lexicallisttype"],
            "ol": ["start", "__lexicallisttype"],
            "li": ["value", "role", "aria-checked"],
            "td": ["colspan", "rowspan"],
            "th": ["colspan", "rowspan", "scope"],
            "col": ["span"],
        },
        css_sanitizer=EDITOR_CSS,
        protocols=["http", "https", "mailto"],
        strip=True,
    )


def prepare_content(
    content: str, user: AbstractBloomerpUser, conversation: IMConversation
) -> tuple[str, str]:
    """Validate tagged targets and replace browser-provided labels before persistence."""
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


def format_content(content: str, target: Literal["plain", "slack", "whatsapp"]) -> str:
    """Flatten HTML into plain text or the provider's supported messaging markup.

    Object references become labels, never external mentions or internal URLs.
    Slack control characters are escaped to prevent forged mention/link syntax.
    """
    soup = BeautifulSoup(sanitize_html(content), "html.parser")
    return "".join(format_node(node, target) for node in soup.children).strip()


def format_node(node: Tag | NavigableString, target: str) -> str:
    """Render one inert HTML node while preserving inline text and block breaks."""
    if isinstance(node, NavigableString):
        return escape(str(node), quote=False) if target == "slack" else str(node)
    if node.get("data-reference-kind"):
        label = node.get_text()
        return escape(label, quote=False) if target == "slack" else label
    text = "".join(format_node(child, target) for child in node.children)
    if node.name == "br":
        return "\n"
    if node.name == "a" and node.get("href"):
        url = str(node["href"])
        if (
            url.startswith(("https://", "http://", "mailto:"))
            and url != node.get_text()
        ):
            if target == "slack":
                return (
                    "<"
                    + escape(url.replace("|", "%7C"), quote=False)
                    + "|"
                    + text.replace("|", " ")
                    + ">"
                )
            return text + " (" + url + ")"
    if target != "plain":
        marker = {
            "b": "*",
            "strong": "*",
            "i": "_",
            "em": "_",
            "s": "~",
            "del": "~",
            "code": "```" if target == "whatsapp" else "`",
            "pre": "```",
        }.get(node.name)
        if marker and text.strip():
            equivalent = {
                "b": "strong",
                "strong": "strong",
                "i": "em",
                "em": "em",
                "s": "del",
                "del": "del",
            }
            if (
                isinstance(node.parent, Tag)
                and node.name in equivalent
                and equivalent.get(node.parent.name) == equivalent[node.name]
            ):
                return text
            # Avoid nested code fences emitted by editors as pre > code.
            if node.name == "pre":
                text = node.get_text().replace("`", "ˋ")
                if target == "slack":
                    text = escape(text, quote=False)
            return marker + text + marker + ("\n" if node.name == "pre" else "")
    if node.name == "li":
        return "• " + text.strip() + "\n"
    if node.name == "blockquote":
        return "\n".join("> " + line for line in text.strip().splitlines()) + "\n"
    if node.name in ("p", "pre", "ul", "ol", "h1", "h2", "h3"):
        return text.rstrip("\n") + "\n"
    return text


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
