from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse

from bloomerp.communication.builtins.emails.base_adapter import (
    BloomerpEmail,
    EmailAttachment,
)
from bloomerp.communication.builtins.emails.email_providers import (
    EmailProviderDefinition,
)
from bloomerp.communication.builtins.emails.mailboxes import (
    merge_mailboxes,
    normalize_mailboxes,
)
from bloomerp.communication.builtins.emails.registry import EMAIL_PROVIDER_REGISTRY
from bloomerp.models.communication.email_account import EmailAccount

if TYPE_CHECKING:
    from bloomerp.communication.builtins.emails.base_adapter import BaseEmailAdapter
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

DEEP_QUERY_LIMIT = 50
DEFAULT_MAILBOX = "INBOX"


def _resolve_provider(email_account: EmailAccount) -> EmailProviderDefinition:
    provider = EMAIL_PROVIDER_REGISTRY.get(email_account.provider)
    if provider is None:
        raise ValueError(f"Unsupported email provider: {email_account.provider}")
    return provider


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
    provider_location = _resolve_provider_location(inbox_item)
    if provider_location is None:
        raise ValidationError(
            "This email is not connected to a synchronized provider message."
        )

    metadata = inbox_item.raw_meta_data or {}
    provider_message_id, mailbox = provider_location
    email_account_id = metadata.get("email_account_id")
    if not email_account_id:
        email_account_id = inbox_item.folder.related_object_id
    email_account = get_object_or_404(EmailAccount, id=email_account_id)

    return (
        _resolve_email_adapter_for_account(email_account),
        provider_message_id,
        mailbox,
    )


def _resolve_provider_location(inbox_item: "InboxItem") -> tuple[str, str] | None:
    """Return a provider UID and mailbox without guessing from RFC Message-ID."""
    metadata = inbox_item.raw_meta_data or {}
    locations = metadata.get("locations") or {}
    location = locations.get(DEFAULT_MAILBOX)
    if location is None and locations:
        location = next(iter(locations.values()))

    if location is not None:
        provider_message_id = location.get("provider_message_id")
        if provider_message_id:
            return (
                str(provider_message_id),
                str(location.get("mailbox") or DEFAULT_MAILBOX),
            )

    provider_message_id = metadata.get("provider_message_id")
    if provider_message_id:
        return (
            str(provider_message_id),
            str(metadata.get("mailbox") or DEFAULT_MAILBOX),
        )
    return None


def _is_locally_stored_outbound_email(inbox_item: "InboxItem") -> bool:
    metadata = inbox_item.raw_meta_data or {}
    return metadata.get("outbound_body_html") is not None


def render_email(inbox_item:"InboxItem", request: HttpRequest) -> str:
    """Render email content, attachments, and policy-authorized calendar response controls."""
    from bloomerp.communication.calendar.access import invitation_context

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
            "calendar_invitation": invitation_context(inbox_item, request.user),
            "calendar_needs_review": any(result.get("outcome") == "requires_review" for result in metadata.get("calendar_processing", [])),
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
    if not (
        _is_locally_stored_outbound_email(inbox_item)
        and _resolve_provider_location(inbox_item) is None
    ):
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
    if (
        _is_locally_stored_outbound_email(inbox_item)
        and _resolve_provider_location(inbox_item) is None
    ):
        inbox_item.delete()
        return

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
    """Apply mailbox, search and shared predicates before deciding whether to fetch emails."""
    from bloomerp.communication.common.queries import apply_inbox_filters
    from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

    queryset = InboxItem.objects.filter(
        folder=folder,
        item_type=INBOX_FOLDER_REGISTRY.EMAIL.item_type.key,
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

    return apply_inbox_filters(queryset, filters).distinct().order_by(
        "-datetime_received", "-datetime_created"
    )


def _upsert_email_inbox_item_result(
    email: BloomerpEmail,
    folder: "InboxFolder",
) -> tuple["InboxItem", bool]:
    """Correlate provider and RFC identities, update locations, and process scheduling content."""
    from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

    related_item_id = (
        email.message_id.strip()
        if email.message_id and email.message_id.strip()
        else (
            f"{email.provider}:{email.provider_message_id}"
            if email.provider_message_id_scope == "account"
            else f"{email.provider}:{email.mailbox}:{email.provider_message_id}"
        )
    )
    provider_metadata = email.retrieval_metadata()

    with transaction.atomic():
        inbox_item = None
        if email.provider_message_id_scope == "account":
            inbox_item = InboxItem.objects.select_for_update().filter(
                item_type=INBOX_FOLDER_REGISTRY.EMAIL.item_type.key,
                folder=folder,
                raw_meta_data__provider=email.provider,
                raw_meta_data__provider_identity=email.provider_message_id,
            ).first()
        if inbox_item is None:
            inbox_item, created = InboxItem.objects.get_or_create(
                item_type=INBOX_FOLDER_REGISTRY.EMAIL.item_type.key,
                folder=folder,
                related_item_id=related_item_id,
                defaults={"title": email.subject or "(No subject)"},
            )
        else:
            created = False
        if not created:
            inbox_item = InboxItem.objects.select_for_update().get(pk=inbox_item.pk)
        if email.message_id and inbox_item.related_item_id != related_item_id:
            canonical = InboxItem.objects.select_for_update().filter(
                folder=folder,
                item_type=INBOX_FOLDER_REGISTRY.EMAIL.item_type.key,
                related_item_id=related_item_id,
            ).first()
            if canonical is not None:
                previous_metadata = dict(inbox_item.raw_meta_data or {})
                canonical_metadata = dict(canonical.raw_meta_data or {})
                canonical.raw_meta_data = {
                    **previous_metadata,
                    **canonical_metadata,
                    "locations": {
                        **(previous_metadata.get("locations") or {}),
                        **(canonical_metadata.get("locations") or {}),
                    },
                }
                inbox_item.delete()
                inbox_item = canonical
            else:
                inbox_item.related_item_id = related_item_id
        if email.provider_message_id_scope == "account":
            provider_metadata["provider_identity"] = email.provider_message_id

        metadata = dict(inbox_item.raw_meta_data or {})
        if not email.is_draft:
            metadata.pop("outbound_send_pending", None)
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
        if not email.is_draft:
            from bloomerp.models.communication.email_draft import EmailDraft

            EmailDraft.clear_pending_send(
                account_id=email.email_account_id,
                provider_message_id=email.provider_message_id,
                mailbox=email.mailbox,
                provider_message_id_scope=email.provider_message_id_scope,
            )
        if email.calendar_parts:
            from bloomerp.communication.calendar.incoming import process_calendar_email

            account = _resolve_email_account_from_folder(folder)
            sent_mailboxes = {name for name, settings in normalize_mailboxes(account.mailboxes).items() if settings["sent_folder"]}
            if email.mailbox not in sent_mailboxes:
                process_calendar_email(email, folder, inbox_item)
    return inbox_item, created


def _remove_email_provider_locations(
    folders: list["InboxFolder"],
    *,
    mailbox: str,
    provider_message_ids: list[str],
) -> int:
    """Remove vanished mailbox references, deleting items only after their last location."""
    from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

    if not provider_message_ids:
        return 0
    lookup = f"raw_meta_data__locations__{mailbox}__provider_message_id__in"
    items = InboxItem.objects.select_for_update().filter(
        folder__in=folders,
        item_type=INBOX_FOLDER_REGISTRY.EMAIL.item_type.key,
    ).filter(
        Q(**{lookup: provider_message_ids})
        | Q(
            raw_meta_data__mailbox=mailbox,
            raw_meta_data__provider_message_id__in=provider_message_ids,
        )
    )
    removed_count = 0
    for item in items:
        metadata = dict(item.raw_meta_data or {})
        locations = dict(metadata.get("locations") or {})
        locations.pop(mailbox, None)
        if not locations:
            item.delete()
        else:
            metadata["locations"] = locations
            if metadata.get("mailbox") == mailbox:
                for field in ("mailbox", "provider_message_id", "flags", "raw"):
                    metadata.pop(field, None)
            item.raw_meta_data = metadata
            item.save(update_fields=["raw_meta_data"])
        removed_count += 1
    return removed_count


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
    filters = dict(filters or {})
    if "mailbox" not in filters:
        account = folder.related_object()
        mapping = normalize_mailboxes(account.mailboxes) if account else {}
        main = next((name for name, settings in mapping.items() if settings["main_folder"]), None)
        if main:
            filters["mailbox"] = main
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
    """Discover provider labels and roles without discarding user mailbox configuration."""
    provider = _resolve_provider(email_account)
    adapter = _resolve_email_adapter_for_account(email_account)
    try:
        mailboxes = adapter.list_mailboxes()
        defaults = provider.mailbox_defaults(adapter) if provider.mailbox_defaults else None
        email_account.mailboxes = merge_mailboxes(
            mailboxes,
            email_account.mailboxes,
            provider_defaults=defaults,
        )
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()
    if save:
        email_account.save(update_fields=["mailboxes", "datetime_updated"])
    return mailboxes
