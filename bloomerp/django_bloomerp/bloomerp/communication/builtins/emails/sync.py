"""Email synchronization policy and inbox-source handlers."""

import datetime
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from bloomerp.communication.builtins.emails.actions import (
    DEFAULT_MAILBOX,
    _resolve_email_adapter_for_account,
    _upsert_email_inbox_item_result,
)
from bloomerp.communication.builtins.emails.email_providers import (
    EmailProviderDefinition,
    EmailSyncMode,
)
from bloomerp.communication.builtins.emails.registry import EMAIL_PROVIDER_REGISTRY
from bloomerp.communication.builtins.emails.mailboxes import normalize_mailboxes
from bloomerp.communication.inbox_sources import (
    InboxSourceDelivery,
    InboxSourceExecutionResult,
    publish_event,
)
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder


DEFAULT_SYNC_LIMIT = 50
SYNC_LOCK_MINUTES = 15


def _account_sync_mode(email_account: EmailAccount) -> str | None:
    provider = EMAIL_PROVIDER_REGISTRY.get(email_account.provider)
    if provider is None:
        return email_account.sync_mode or None
    provider_definition: EmailProviderDefinition = provider
    return email_account.sync_mode or provider_definition.sync_capabilities.default_mode.value


def _next_sync_at(email_account: EmailAccount) -> datetime.datetime:
    provider = EMAIL_PROVIDER_REGISTRY.get(email_account.provider)
    interval_minutes = email_account.sync_interval_minutes
    if not interval_minutes and provider is not None:
        interval_minutes = provider.sync_capabilities.default_poll_interval_minutes
    return timezone.now() + timedelta(minutes=interval_minutes or 5)


def resolve_email_folders(
    *,
    email_account_id: str | None = None,
    **kwargs,
) -> QuerySet[InboxFolder]:
    """Resolve email folders, optionally scoped to one account."""
    from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY

    folders = InboxFolder.objects.filter(type=INBOX_FOLDER_REGISTRY.EMAIL.key)
    if email_account_id is not None:
        folders = folders.filter(related_object_id=str(email_account_id))
    return folders


def handle_email_account_sync(
    folders: QuerySet[InboxFolder],
    *,
    email_account_id: str,
    from_date: datetime.date | datetime.datetime | None = None,
    to_date: datetime.date | datetime.datetime | None = None,
    limit: int = DEFAULT_SYNC_LIMIT,
    mailboxes: list[str] | None = None,
    **kwargs: Any,
) -> InboxSourceExecutionResult:
    """Synchronize one account and deliver new messages outside its configured Sent mailbox."""
    email_account = EmailAccount.objects.get(pk=email_account_id)
    now = timezone.now()
    lock_acquired = (
        EmailAccount.objects
        .filter(pk=email_account.pk)
        .filter(Q(sync_locked_until__isnull=True) | Q(sync_locked_until__lt=now))
        .update(
            sync_locked_until=now + timedelta(minutes=SYNC_LOCK_MINUTES),
            last_sync_started_at=now,
            last_sync_error="",
        )
    )
    if not lock_acquired:
        return InboxSourceExecutionResult(
            outcome="skipped",
            reason="account_locked",
            metrics={"email_account_id": str(email_account.pk)},
        )

    folders = list(folders)
    try:
        if _account_sync_mode(email_account) != EmailSyncMode.POLLING.value:
            result = InboxSourceExecutionResult(
                outcome="skipped",
                reason="not_polling",
                metrics={"email_account_id": str(email_account.pk)},
            )
        elif not folders:
            result = InboxSourceExecutionResult(
                outcome="skipped",
                reason="no_linked_folders",
                metrics={"email_account_id": str(email_account.pk)},
            )
        else:
            mailbox_mapping = normalize_mailboxes(email_account.mailboxes or {})
            sent_mailboxes = {
                mailbox for mailbox, settings in mailbox_mapping.items()
                if settings["sent_folder"]
            }
            selected_mailboxes = [mailbox for mailbox in (mailboxes or []) if mailbox]
            if not selected_mailboxes:
                selected_mailboxes = [
                    mailbox for mailbox in (email_account.mailboxes or []) if mailbox
                ] or [DEFAULT_MAILBOX]

            emails = []
            for mailbox in selected_mailboxes:
                adapter = _resolve_email_adapter_for_account(email_account)
                try:
                    emails.extend(
                        adapter.sync_emails(
                            from_date=from_date,
                            to_date=to_date,
                            limit=limit,
                            mailbox=mailbox,
                        )
                    )
                finally:
                    close = getattr(adapter, "close", None)
                    if callable(close):
                        close()

            deliveries = []
            for folder in folders:
                created_items = []
                sent_item_ids = set()
                with transaction.atomic():
                    for email in emails:
                        inbox_item, created = _upsert_email_inbox_item_result(
                            email,
                            folder,
                        )
                        if email.mailbox in sent_mailboxes:
                            sent_item_ids.add(inbox_item.pk)
                        if created:
                            created_items.append(inbox_item)
                created_items = [
                    item for item in created_items if item.pk not in sent_item_ids
                ]
                if created_items:
                    deliveries.append(
                        InboxSourceDelivery(
                            folder=folder,
                            items=tuple(created_items),
                        )
                    )

            result = InboxSourceExecutionResult(
                deliveries=tuple(deliveries),
                metrics={
                    "email_account_id": str(email_account.pk),
                    "fetched_messages": len(emails),
                    "mailboxes": len(selected_mailboxes),
                },
            )
    except Exception as exc:
        email_account.refresh_from_db()
        email_account.last_sync_error = str(exc)
        email_account.next_sync_at = _next_sync_at(email_account)
        email_account.sync_locked_until = None
        email_account.save(
            update_fields=[
                "last_sync_error",
                "next_sync_at",
                "sync_locked_until",
                "datetime_updated",
            ]
        )
        raise

    email_account.refresh_from_db()
    email_account.last_sync_finished_at = timezone.now()
    email_account.last_sync_error = ""
    email_account.next_sync_at = _next_sync_at(email_account)
    email_account.sync_locked_until = None
    email_account.save(
        update_fields=[
            "last_sync_finished_at",
            "last_sync_error",
            "next_sync_at",
            "sync_locked_until",
            "datetime_updated",
        ]
    )
    return result


def dispatch_due_email_syncs_source(
    folders: QuerySet[InboxFolder],
    *args,
    **kwargs,
) -> InboxSourceExecutionResult:
    """Schedule one source execution for each due polling account."""
    due_accounts = (
        EmailAccount.objects
        .filter(status=EmailAccount.Status.ACTIVE, sync_enabled=True)
        .filter(Q(next_sync_at__isnull=True) | Q(next_sync_at__lte=timezone.now()))
        .only("id", "provider", "sync_mode")
    )

    scheduled_count = 0
    completed_count = 0
    for email_account in due_accounts:
        if _account_sync_mode(email_account) != EmailSyncMode.POLLING.value:
            continue
        receipt = publish_event(
            "email.sync.account",
            email_account_id=str(email_account.pk),
        )
        if receipt.state == "scheduled":
            scheduled_count += 1
        else:
            completed_count += 1

    return InboxSourceExecutionResult(
        metrics={
            "scheduled_accounts": scheduled_count,
            "synchronously_completed_accounts": completed_count,
        }
    )
