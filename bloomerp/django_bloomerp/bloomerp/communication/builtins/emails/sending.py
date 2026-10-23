"""Provider-neutral outbound identities and local reconciliation records."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _

from bloomerp.communication.builtins.emails.base_adapter import EmailSendResult
from bloomerp.communication.builtins.emails.mailboxes import normalize_mailboxes

if TYPE_CHECKING:
    from bloomerp.models.communication.email_account import EmailAccount
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.communication.inbox.inbox_item import InboxItem


UNCONFIRMED_SEND_MESSAGE = _(
    "The provider did not confirm delivery. Check Sent Items and Drafts before sending again."
)


def outbound_message_id(result: str | EmailSendResult) -> str:
    """Return the RFC Message-ID without substituting a remote retrieval identifier."""
    if isinstance(result, EmailSendResult):
        return result.message_id or ""
    return result


def outbound_metadata(
    account: EmailAccount, result: str | EmailSendResult, *, pending: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Keep RFC threading and provider retrieval identities distinct for reconciliation."""
    sent_mailbox = next(
        (name for name, settings in normalize_mailboxes(account.mailboxes).items() if settings["sent_folder"]),
        result.mailbox if isinstance(result, EmailSendResult) else "",
    )
    message_id = outbound_message_id(result)
    metadata: dict[str, Any] = {
        "provider": account.provider,
        "mailbox": sent_mailbox,
        "message_id": message_id,
        "email_account_id": str(account.pk),
        "outbound_send_pending": pending,
    }
    related_id = message_id
    if isinstance(result, EmailSendResult):
        metadata.update(
            provider_message_id=result.provider_message_id,
            provider_message_id_scope=result.provider_message_id_scope,
        )
        if result.provider_message_id_scope == "account":
            metadata["provider_identity"] = result.provider_message_id
        related_id = message_id or (
            f"{account.provider}:{result.provider_message_id}"
            if result.provider_message_id_scope == "account"
            else f"{account.provider}:{sent_mailbox}:{result.provider_message_id}"
        )
    return related_id, metadata


def store_outbound_email(
    *, account: EmailAccount, result: str | EmailSendResult,
    form_data: dict[str, Any], body_html: str,
    folders: Iterable[InboxFolder] | None = None,
    original: InboxItem | None = None,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
    pending: bool = False,
) -> list[InboxItem]:
    """Persist sent or uncertain messages so a later provider sync reuses their identity."""
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

    related_id, metadata = outbound_metadata(account, result, pending=pending)
    metadata.update(
        to=form_data.get("to", []), cc=form_data.get("cc", []),
        in_reply_to=in_reply_to, references=references or [],
        outbound_body_html=body_html,
    )
    selected_folders = folders if folders is not None else InboxFolder.objects.filter(
        type="email", related_object_id=str(account.pk),
    )
    stored: list[InboxItem] = []
    with transaction.atomic():
        if original is not None:
            original_metadata = dict(original.raw_meta_data or {})
            conversation_id = str(original_metadata.get("conversation_id") or original.pk)
            original_metadata["conversation_id"] = conversation_id
            InboxItem.objects.filter(pk=original.pk).update(raw_meta_data=original_metadata)
            original.raw_meta_data = original_metadata
            metadata.update(conversation_id=conversation_id, parent_item_id=str(original.pk))
        for folder in selected_folders:
            item, _created = InboxItem.objects.update_or_create(
                folder=folder, item_type="email", related_item_id=related_id,
                defaults={
                    "actor": account.email_address,
                    "is_read": True,
                    "datetime_received": timezone.now(),
                    "title": str(form_data.get("subject") or ""),
                    "snippet": strip_tags(str(form_data.get("body") or body_html))[:500],
                    "raw_meta_data": metadata,
                },
            )
            stored.append(item)
    return stored
