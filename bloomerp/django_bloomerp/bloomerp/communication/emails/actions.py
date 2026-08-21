from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse

from bloomerp.communication.emails.base_adapter import BloomerpEmail, EmailAttachment
from bloomerp.communication.emails.email_providers import EmailProvider, EmailProviderDefinition
from bloomerp.models.communication.email_account import EmailAccount

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.communication.inbox.inbox_item import InboxItem
    from bloomerp.communication.emails.base_adapter import BaseEmailAdapter

DEEP_QUERY_LIMIT = 50
DEFAULT_MAILBOX = "INBOX"


def _resolve_provider(email_account: EmailAccount) -> EmailProviderDefinition:
    provider = EmailProvider.from_key(email_account.provider)
    if provider is None:
        raise ValueError(f"Unsupported email provider: {email_account.provider}")
    return provider.value


def _resolve_email_adapter_for_account(email_account: EmailAccount) -> "BaseEmailAdapter":
    provider = _resolve_provider(email_account)
    return provider.adapter_class(email_account=email_account)


def _resolve_email_account_from_folder(folder: "InboxFolder") -> EmailAccount:
    if not folder.related_object_id:
        raise EmailAccount.DoesNotExist("Email inbox folder is not connected to an email account.")
    return get_object_or_404(EmailAccount, id=folder.related_object_id)


def _resolve_email_access(
    inbox_item: "InboxItem",
) -> tuple["BaseEmailAdapter", str, str]:
    metadata = inbox_item.raw_meta_data or {}
    locations = metadata.get("locations") or {}
    location = locations.get(DEFAULT_MAILBOX)
    if location is None and locations:
        location = next(iter(locations.values()))

    email_account_id = metadata.get("email_account_id")
    if not email_account_id:
        email_account_id = inbox_item.folder.related_object_id
    email_account = get_object_or_404(EmailAccount, id=email_account_id)

    if location is not None:
        return (
            _resolve_email_adapter_for_account(email_account),
            str(location["provider_message_id"]),
            str(location["mailbox"]),
        )

    return (
        _resolve_email_adapter_for_account(email_account),
        str(metadata.get("provider_message_id") or inbox_item.related_item_id),
        str(metadata.get("mailbox") or DEFAULT_MAILBOX),
    )


def render_email(inbox_item:"InboxItem", request: HttpRequest) -> str:
    """_summary_

    Args:
        inbox_item (InboxItem): _description_
        request (HttpRequest): _description_

    Returns:
        str: _description_
    """
    metadata = inbox_item.raw_meta_data or {}
    content = metadata.get("outbound_body_html")
    if content is None:
        content = fetch_email_content(inbox_item)

    attachment_metadata = metadata.get("attachments") or []
    files = [
        {
            **attachment,
            "download_url": reverse(
                "components_emails_download_attachment",
                kwargs={
                    "inbox_item_id": inbox_item.pk,
                    "attachment_id": attachment["id"],
                },
            ),
        }
        for attachment in attachment_metadata
    ]
    return render_to_string(
        "inbox_items/email.html",
        {
            "content": content,
            "files": files,
        },
        request=request,
    )


def fetch_email_content(inbox_item: "InboxItem") -> str:
    """Fetch an email body, falling back to a locally stored outbound body."""
    stored_content = (inbox_item.raw_meta_data or {}).get("outbound_body_html")
    if stored_content is not None:
        return str(stored_content)

    adapter, provider_message_id, mailbox = _resolve_email_access(inbox_item)
    try:
        return adapter.fetch_email_content(
            email_id=provider_message_id,
            mailbox=mailbox,
        )
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()


def fetch_email_attachment(
    inbox_item: "InboxItem",
    attachment_id: str,
) -> EmailAttachment:
    """Fetch a referenced attachment without persisting its binary content."""
    attachments = (inbox_item.raw_meta_data or {}).get("attachments") or []
    attachment_metadata = next(
        (
            attachment
            for attachment in attachments
            if str(attachment.get("id")) == attachment_id
        ),
        None,
    )
    if attachment_metadata is None:
        raise Http404("Attachment not found.")

    adapter, provider_message_id, mailbox = _resolve_email_access(inbox_item)
    try:
        attachment = adapter.fetch_email_attachment(
            email_id=provider_message_id,
            attachment_id=attachment_id,
            mailbox=mailbox,
        )
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()

    if attachment is None:
        raise Http404("Attachment not found.")
    return EmailAttachment(
        filename=str(attachment_metadata.get("filename") or attachment.filename),
        content=attachment.content,
        content_type=attachment.content_type,
    )


def mark_email_as_read(inbox_item:"InboxItem", request: HttpRequest):
    adapter, provider_message_id, mailbox = _resolve_email_access(inbox_item)
    try:
        adapter.mark_as_read(email_id=provider_message_id, mailbox=mailbox)
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()
    inbox_item.is_read = True
    inbox_item.save(update_fields=["is_read"])


def delete_email(inbox_item:"InboxItem", request: HttpRequest):
    adapter, provider_message_id, mailbox = _resolve_email_access(inbox_item)
    try:
        adapter.delete_email(email_id=provider_message_id, mailbox=mailbox)
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()


def _query_local_email_items(
    filters: dict[str, str] | None,
    folder: "InboxFolder",
) -> QuerySet["InboxItem"]:
    from bloomerp.communication.inbox_folder_definition import InboxFolderType
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

    queryset = InboxItem.objects.filter(
        folder=folder,
        item_type=InboxFolderType.EMAIL.value.item_type.key,
    )

    search_string = (filters or {}).get("q")
    if search_string:
        queryset = queryset.filter(
            Q(title__icontains=search_string)
            | Q(snippet__icontains=search_string)
            | Q(actor__icontains=search_string)
        )

    mailbox = (filters or {}).get("mailbox")
    if mailbox:
        location_lookup = (
            f"raw_meta_data__locations__{mailbox}__"
            "provider_message_id__isnull"
        )
        queryset = queryset.filter(
            Q(**{location_lookup: False})
            | Q(raw_meta_data__mailbox=mailbox)
        )

    is_read_filter = (filters or {}).get("is_read")
    if is_read_filter is not None:
        from bloomerp.utils.requests import parse_bool_parameter

        queryset = queryset.filter(is_read=parse_bool_parameter(is_read_filter))

    return queryset.distinct().order_by("-datetime_received", "-datetime_created")


def _upsert_email_inbox_item_result(
    email: BloomerpEmail,
    folder: "InboxFolder",
) -> tuple["InboxItem", bool]:
    from bloomerp.communication.inbox_folder_definition import InboxFolderType
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

    related_item_id = (
        email.message_id.strip()
        if email.message_id and email.message_id.strip()
        else f"{email.provider}:{email.mailbox}:{email.provider_message_id}"
    )
    provider_metadata = email.retrieval_metadata()

    with transaction.atomic():
        inbox_item, created = InboxItem.objects.get_or_create(
            item_type=InboxFolderType.EMAIL.value.item_type.key,
            folder=folder,
            related_item_id=related_item_id,
            defaults={"title": email.subject or "(No subject)"},
        )
        if not created:
            inbox_item = InboxItem.objects.select_for_update().get(pk=inbox_item.pk)

        metadata = dict(inbox_item.raw_meta_data or {})
        locations = dict(metadata.get("locations") or {})
        locations[email.mailbox] = {
            "mailbox": email.mailbox,
            "provider_message_id": email.provider_message_id,
            "flags": provider_metadata.get("flags") or [],
            "raw": provider_metadata.get("raw") or {},
        }
        for location_field in ("provider_message_id", "mailbox", "flags", "raw"):
            provider_metadata.pop(location_field, None)

        inbox_item.title = email.subject or "(No subject)"
        inbox_item.snippet = email.snippet
        inbox_item.actor = email.sender
        inbox_item.is_read = email.is_read
        inbox_item.raw_meta_data = {
            **metadata,
            **provider_metadata,
            "locations": locations,
        }
        inbox_item.datetime_received = email.date
        inbox_item.save()
    return inbox_item, created


def _upsert_email_inbox_item(email: BloomerpEmail, folder: "InboxFolder") -> "InboxItem":
    inbox_item, _ = _upsert_email_inbox_item_result(email, folder)
    return inbox_item


def query_emails(
    filters: dict[str, str] | None,
    folder: "InboxFolder",
    deep_query: bool,
) -> QuerySet["InboxItem"]:
    """
    Query emails based on the provided filters.

    Args:
        filters (dict[str, str]): A dictionary of filter parameters.
        folder (InboxFolder): The email inbox folder to query.
        deep_query (bool): If True, perform a deep query; otherwise, perform a shallow query.

    Returns:
        QuerySet[InboxItem]: Matching email inbox items.
    """
    filters = filters or {}
    mailbox = filters.get("mailbox") or DEFAULT_MAILBOX
    
    local_queryset = _query_local_email_items(filters, folder)
    if deep_query and not local_queryset.exists():
        email_account = _resolve_email_account_from_folder(folder)
        adapter = _resolve_email_adapter_for_account(email_account)
        search_string = (filters or {}).get("q")

        try:
            emails = adapter.search_emails(
                search_string,
                mailbox=mailbox,
                limit=DEEP_QUERY_LIMIT,
            )
        finally:
            close = getattr(adapter, "close", None)
            if callable(close):
                close()

        for email in emails:
            _upsert_email_inbox_item(email, folder)

        local_queryset = _query_local_email_items(filters, folder)

    return local_queryset
        

def get_mailboxes_for_account(email_account: EmailAccount) -> list[str]:
    """Syncs the email account's mailboxes with the local database.

    Args:
        email_account (EmailAccount): email account to sync mailboxes for

    Returns:
        list[str]: List of synced mailbox names.
    """
    adapter = _resolve_email_adapter_for_account(email_account)
    try:
        mailboxes = adapter.list_mailboxes()
        return mailboxes
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()


def refresh_mailboxes_for_account(email_account: EmailAccount, *, save: bool = True) -> list[str]:
    mailboxes = get_mailboxes_for_account(email_account)
    email_account.mailboxes = mailboxes
    if save:
        email_account.save(update_fields=["mailboxes", "datetime_updated"])
    return mailboxes
