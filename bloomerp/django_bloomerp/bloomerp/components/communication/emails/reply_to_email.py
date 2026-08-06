import re
from email.utils import getaddresses
from typing import TYPE_CHECKING

import bleach
from bleach.css_sanitizer import CSSSanitizer
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.html import strip_tags
from django.utils.translation import gettext as _

from bloomerp.communication.emails.actions import (
    _resolve_email_adapter_for_account,
    fetch_email_content,
)
from bloomerp.communication.utils.permissions import accessible_inbox_items
from bloomerp.components.communication.emails.new_email import (
    _get_attachments,
    _get_form_data,
    _join_recipients,
    _validate_form_data,
)
from bloomerp.router import router
from bloomerp.utils.requests import render_message

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_item import InboxItem


MESSAGE_ID_PATTERN = re.compile(r"<[^<>]+>")
QUOTED_EMAIL_ALLOWED_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "del",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
QUOTED_EMAIL_ALLOWED_ATTRIBUTES = {
    "*": ["style"],
    "a": ["href", "title"],
    "img": ["alt", "height", "src", "title", "width"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}
QUOTED_EMAIL_CSS_SANITIZER = CSSSanitizer(
    allowed_css_properties={
        "background-color",
        "border",
        "border-bottom",
        "border-collapse",
        "border-left",
        "border-right",
        "border-top",
        "color",
        "display",
        "font-family",
        "font-size",
        "font-style",
        "font-weight",
        "height",
        "line-height",
        "margin",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "margin-top",
        "max-width",
        "padding",
        "padding-bottom",
        "padding-left",
        "padding-right",
        "padding-top",
        "text-align",
        "text-decoration",
        "vertical-align",
        "white-space",
        "width",
    }
)


def resolve_inbox_item(
    request: HttpRequest,
    inbox_item_or_id: "InboxItem | str | None",
) -> "InboxItem | None":
    """Resolve an accessible email InboxItem from an instance or request ID."""
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

    if isinstance(inbox_item_or_id, InboxItem):
        return inbox_item_or_id

    item_id = (
        inbox_item_or_id
        or request.GET.get("item_id")
        or request.POST.get("reply_to_item_id")
        or request.POST.get("item_id")
    )
    if not item_id:
        return None

    return get_object_or_404(
        accessible_inbox_items(request.user).filter(item_type="email"),
        id=item_id,
    )


def original_sender_email(inbox_item: "InboxItem") -> str | None:
    """Return the first valid address from an inbox item's sender value."""
    for _, email_address in getaddresses([inbox_item.actor or ""]):
        try:
            validate_email(email_address)
        except ValidationError:
            continue
        return email_address
    return None


def email_reply_is_available(inbox_item: "InboxItem") -> bool:
    """Return whether an email item has a valid sender to reply to."""
    return inbox_item.item_type == "email" and original_sender_email(inbox_item) is not None


def sanitize_quoted_email_html(content: str) -> str:
    """Sanitize inbound email HTML while retaining common email formatting."""
    return bleach.clean(
        content or "",
        tags=QUOTED_EMAIL_ALLOWED_TAGS,
        attributes=QUOTED_EMAIL_ALLOWED_ATTRIBUTES,
        protocols={"cid", "http", "https", "mailto"},
        css_sanitizer=QUOTED_EMAIL_CSS_SANITIZER,
        strip=True,
        strip_comments=True,
    )


@router.register(
    path="components/communication/emails/reply_to_email",
    url_name="components_reply_to_email",
)
@login_required
def reply_to_email(
    request: HttpRequest,
    inbox_item_or_id: "InboxItem | str | None" = None,
) -> HttpResponse:
    """Render or send a reply to an accessible email inbox item."""
    inbox_item = resolve_inbox_item(request, inbox_item_or_id)
    if inbox_item is None:
        return render_message(request, _("Select an email before replying."), "warning")

    sender_email = original_sender_email(inbox_item)
    if sender_email is None:
        return render_message(
            request,
            _("This email does not have a valid sender address."),
            "warning",
        )

    inbox_folder = inbox_item.folder
    email_account = inbox_folder.related_object()
    if email_account is None:
        return render_message(
            request,
            _("This email folder is not connected to an email account."),
            "error",
        )

    quoted_email = _quoted_email_context(inbox_item)
    if request.method == "POST":
        return _send_reply(
            request,
            inbox_item=inbox_item,
            inbox_folder=inbox_folder,
            email_account=email_account,
            quoted_email=quoted_email,
        )

    return _render_reply_composer(
        request,
        inbox_item=inbox_item,
        inbox_folder=inbox_folder,
        email_account=email_account,
        quoted_email=quoted_email,
        form_data={
            "to": [sender_email],
            "cc": [],
            "bcc": [],
            "subject": _reply_subject(inbox_item.title),
            "body": "",
        },
    )


def _send_reply(
    request: HttpRequest,
    *,
    inbox_item: "InboxItem",
    inbox_folder,
    email_account,
    quoted_email: dict[str, str],
) -> HttpResponse:
    """Validate, send, and persist one reply."""
    form_data = _get_form_data(request)
    errors = _validate_form_data(form_data)
    if errors:
        return _render_reply_composer(
            request,
            inbox_item=inbox_item,
            inbox_folder=inbox_folder,
            email_account=email_account,
            quoted_email=quoted_email,
            form_data=form_data,
            errors=errors,
        )

    in_reply_to = _original_message_id(inbox_item)
    references = _reply_references(inbox_item, in_reply_to)
    quoted_html = render_to_string(
        "components/communication/emails/quoted_email.html",
        {"quoted_email": quoted_email},
        request=request,
    )
    body_html = f'{form_data["body"]}{quoted_html}'
    attachments = _get_attachments(request)
    adapter = _resolve_email_adapter_for_account(email_account)
    try:
        sent_message_id = adapter.send_email(
            to=form_data["to"],
            cc=form_data["cc"],
            bcc=form_data["bcc"],
            subject=form_data["subject"],
            body_html=body_html,
            attachments=attachments,
            in_reply_to=in_reply_to,
            references=references,
        )
    except ValidationError as exc:
        return _render_reply_composer(
            request,
            inbox_item=inbox_item,
            inbox_folder=inbox_folder,
            email_account=email_account,
            quoted_email=quoted_email,
            form_data=form_data,
            errors=exc.messages,
        )
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()

    _store_sent_reply(
        inbox_item=inbox_item,
        email_account=email_account,
        sent_message_id=sent_message_id,
        form_data=form_data,
        body_html=body_html,
        in_reply_to=in_reply_to,
        references=references,
    )
    return render_message(request, _("Reply sent successfully."), "success")


def _render_reply_composer(
    request: HttpRequest,
    *,
    inbox_item: "InboxItem",
    inbox_folder,
    email_account,
    quoted_email: dict[str, str],
    form_data: dict[str, object],
    errors: list[str] | None = None,
) -> HttpResponse:
    """Render the reply composer with stable quoted content."""
    return render(
        request,
        "components/communication/emails/email_editor.html",
        {
            "mode": "reply",
            "title": _("Reply"),
            "submit_label": _("Send reply"),
            "inbox_item": inbox_item,
            "inbox_folder": inbox_folder,
            "email_account": email_account,
            "from_email": getattr(email_account, "email_address", ""),
            "to": _join_recipients(form_data.get("to", [])),
            "cc": _join_recipients(form_data.get("cc", [])),
            "bcc": _join_recipients(form_data.get("bcc", [])),
            "subject": form_data.get("subject", ""),
            "body": form_data.get("body", ""),
            "quoted_email": quoted_email,
            "form_action": reverse("components_reply_to_email"),
            "send_enabled": True,
            "errors": errors or [],
        },
    )


def _quoted_email_context(inbox_item: "InboxItem") -> dict[str, str]:
    """Build escaped header values and sanitized HTML for the quoted message."""
    metadata = inbox_item.raw_meta_data or {}
    recipients = metadata.get("to") or []
    if isinstance(recipients, str):
        recipient_text = recipients
    else:
        recipient_text = ", ".join(str(value) for value in recipients)

    sent_at = inbox_item.datetime_received or inbox_item.datetime_created
    if sent_at and timezone.is_aware(sent_at):
        sent_at = timezone.localtime(sent_at)

    return {
        "from": inbox_item.actor or "",
        "to": recipient_text,
        "sent": formats.date_format(sent_at, "DATETIME_FORMAT") if sent_at else "",
        "subject": inbox_item.title or "",
        "content_html": sanitize_quoted_email_html(fetch_email_content(inbox_item)),
    }


def _reply_subject(subject: str | None) -> str:
    """Prefix a subject with Re: exactly once."""
    normalized_subject = (subject or "").strip()
    if normalized_subject.lower().startswith("re:"):
        return normalized_subject
    return f"Re: {normalized_subject}".rstrip()


def _original_message_id(inbox_item: "InboxItem") -> str | None:
    """Return the original RFC Message-ID when one is available."""
    metadata = inbox_item.raw_meta_data or {}
    candidate = str(metadata.get("message_id") or inbox_item.related_item_id or "").strip()
    return candidate if MESSAGE_ID_PATTERN.fullmatch(candidate) else None


def _reply_references(
    inbox_item: "InboxItem",
    in_reply_to: str | None,
) -> list[str]:
    """Extend the original References chain with the replied-to message ID."""
    metadata = inbox_item.raw_meta_data or {}
    raw_references = metadata.get("references") or []
    if isinstance(raw_references, str):
        references = MESSAGE_ID_PATTERN.findall(raw_references)
    else:
        references = [
            message_id
            for value in raw_references
            for message_id in MESSAGE_ID_PATTERN.findall(str(value))
        ]

    if not references:
        references.extend(
            MESSAGE_ID_PATTERN.findall(str(metadata.get("in_reply_to") or ""))
        )
    if in_reply_to:
        references.append(in_reply_to)
    return list(dict.fromkeys(references))


def _store_sent_reply(
    *,
    inbox_item: "InboxItem",
    email_account,
    sent_message_id: str,
    form_data: dict[str, object],
    body_html: str,
    in_reply_to: str | None,
    references: list[str],
) -> "InboxItem":
    """Store a sent reply and link it to the original BloomERP conversation."""
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

    original_metadata = dict(inbox_item.raw_meta_data or {})
    conversation_id = str(original_metadata.get("conversation_id") or inbox_item.pk)
    original_metadata["conversation_id"] = conversation_id

    with transaction.atomic():
        InboxItem.objects.filter(pk=inbox_item.pk).update(
            raw_meta_data=original_metadata,
        )
        sent_item, _ = InboxItem.objects.update_or_create(
            folder=inbox_item.folder,
            item_type="email",
            related_item_id=sent_message_id,
            defaults={
                "actor": email_account.email_address,
                "is_read": True,
                "datetime_received": timezone.now(),
                "title": str(form_data["subject"]),
                "snippet": strip_tags(str(form_data["body"]))[:500],
                "raw_meta_data": {
                    "provider": "smtp",
                    "message_id": sent_message_id,
                    "email_account_id": str(email_account.pk),
                    "to": form_data["to"],
                    "cc": form_data["cc"],
                    "in_reply_to": in_reply_to,
                    "references": references,
                    "conversation_id": conversation_id,
                    "parent_item_id": str(inbox_item.pk),
                    "outbound_body_html": body_html,
                },
            },
        )
    inbox_item.raw_meta_data = original_metadata
    return sent_item
