"""Shared request parsing and sender/draft lookup for email endpoints."""

from __future__ import annotations

from email.utils import getaddresses
from typing import Any, TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

from bloomerp.communication.builtins.emails.base_adapter import EmailAttachment
from bloomerp.communication.utils.permissions import accessible_inbox_folders
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.email_draft import EmailDraft
from bloomerp.services.email_composer_services import accessible_email_accounts

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder


def resolve_inbox_folder(
    request: HttpRequest, inbox_folder_or_id: InboxFolder | str | None,
) -> InboxFolder | None:
    """Resolve an accessible email folder, including caller-supplied instances."""
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder

    folder_id = (
        inbox_folder_or_id.pk if isinstance(inbox_folder_or_id, InboxFolder)
        else inbox_folder_or_id or request.GET.get("folder_id") or request.POST.get("folder_id")
    )
    if not folder_id:
        return None
    return get_object_or_404(accessible_inbox_folders(request.user).filter(type="email"), pk=folder_id)


def _resolve_account(request: HttpRequest, folder: InboxFolder | None) -> EmailAccount | None:
    """Select an explicit permitted sender, inbox sender, or accessible default."""
    accounts = accessible_email_accounts(request.user)
    data = request.POST if request.method == "POST" else request.GET
    account_id = data.get("email_account_id")
    if account_id:
        return get_object_or_404(accounts, pk=account_id)
    if folder is not None:
        account = accounts.filter(pk=folder.related_object_id).first()
        if account is not None:
            return account
    return accounts.filter(pk=request.user.default_email_account_id).first() or accounts.first()


def _resolve_draft(request: HttpRequest) -> EmailDraft | None:
    """Only accept a draft owned by the signed-in user."""
    draft_id = request.POST.get("draft_id")
    if not draft_id:
        return None
    try:
        draft_id = UUID(draft_id)
    except ValueError as exc:
        raise ValidationError(_("Invalid draft ID.")) from exc
    return get_object_or_404(EmailDraft, pk=draft_id, user=request.user)


def _get_form_data(request: HttpRequest) -> dict[str, Any]:
    """Normalize recipient lists and trim the submitted subject and message."""
    return {
        "to": _parse_recipients(request.POST.get("to", "")),
        "cc": _parse_recipients(request.POST.get("cc", "")),
        "bcc": _parse_recipients(request.POST.get("bcc", "")),
        "subject": request.POST.get("subject", "").strip(),
        "body": request.POST.get("body", "").strip(),
    }


def _validate_form_data(form_data: dict[str, Any]) -> list[str]:
    """Require a recipient and content while validating each recipient address."""
    errors: list[str] = []
    if not form_data["to"]:
        errors.append(_("Add at least one recipient."))
    for field_name in ("to", "cc", "bcc"):
        for email_address in form_data[field_name]:
            try:
                validate_email(email_address)
            except ValidationError:
                errors.append(_("'%(email)s' is not a valid email address.") % {"email": email_address})
    if not form_data["subject"] and not form_data["body"]:
        errors.append(_("Add a subject or message body before sending."))
    return errors


def _parse_recipients(value: str) -> list[str]:
    """Parse comma- or semicolon-separated RFC mailbox addresses."""
    return [email for _, email in getaddresses([value.replace(";", ",")]) if email]


def _join_recipients(value: object) -> str:
    """Format a recipient list for the email input."""
    return ", ".join(str(item) for item in value) if isinstance(value, list) else str(value or "")


def _get_attachments(request: HttpRequest) -> list[EmailAttachment]:
    """Read uploaded files into the provider's shared attachment contract."""
    return [EmailAttachment(
        filename=uploaded_file.name, content=uploaded_file.read(),
        content_type=uploaded_file.content_type or "application/octet-stream",
    ) for uploaded_file in request.FILES.getlist("attachments") if uploaded_file.size]
