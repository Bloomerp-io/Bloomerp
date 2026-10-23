"""Email synchronization policy and inbox-source handlers."""

import datetime
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from bloomerp.communication.builtins.emails.actions import (
    DEFAULT_MAILBOX,
    _remove_email_provider_locations,
    _resolve_email_adapter_for_account,
    _upsert_email_inbox_item_result,
)
from bloomerp.communication.builtins.emails.base_adapter import (
    BaseEmailAdapter,
    EmailSyncBatch,
)
from bloomerp.communication.builtins.emails.email_providers import (
    EmailProviderDefinition,
    EmailSyncMode,
)
from bloomerp.communication.builtins.emails.mailboxes import normalize_mailboxes
from bloomerp.communication.builtins.emails.registry import EMAIL_PROVIDER_REGISTRY
from bloomerp.communication.inbox_sources import (
    InboxSourceDelivery,
    InboxSourceExecutionResult,
    publish_event,
)
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem

DEFAULT_SYNC_LIMIT = 50
SYNC_LOCK_MINUTES = 15


class _EmailSyncStopped(Exception):
    """Indicate that account availability or lock ownership changed during a sync."""


def _account_sync_mode(email_account: EmailAccount) -> str | None:
    """Resolve the account explicit or registered synchronization mode."""
    provider = EMAIL_PROVIDER_REGISTRY.get(email_account.provider)
    if provider is None:
        return email_account.sync_mode or None
    provider_definition: EmailProviderDefinition = provider
    return email_account.sync_mode or provider_definition.sync_capabilities.default_mode.value


def _next_sync_at(email_account: EmailAccount) -> datetime.datetime:
    """Schedule the next poll using account settings or provider defaults."""
    provider = EMAIL_PROVIDER_REGISTRY.get(email_account.provider)
    interval_minutes = email_account.sync_interval_minutes
    if not interval_minutes and provider is not None:
        interval_minutes = provider.sync_capabilities.default_poll_interval_minutes
    return timezone.now() + timedelta(minutes=interval_minutes or 5)


def resolve_email_folders(
    *,
    email_account_id: str | None = None,
    **kwargs: Any,
) -> QuerySet[InboxFolder]:
    """Resolve email folders, optionally scoped to one account."""
    from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY

    folders = InboxFolder.objects.filter(type=INBOX_FOLDER_REGISTRY.EMAIL.key)
    if email_account_id is not None:
        folders = folders.filter(related_object_id=str(email_account_id))
    return folders


def _lock_owned_account(
    account_id: str,
    lock_owner: datetime.datetime,
) -> EmailAccount:
    """Lock a still-enabled account row while applying one owned sync transaction."""
    account = EmailAccount.objects.select_for_update().get(pk=account_id)
    if account.status != EmailAccount.Status.ACTIVE or not account.sync_enabled:
        raise _EmailSyncStopped("account_unavailable")
    if (
        account.last_sync_started_at != lock_owner
        or account.sync_locked_until is None
        or account.sync_locked_until <= timezone.now()
    ):
        raise _EmailSyncStopped("account_lock_lost")
    return account


def _persist_email_batch(
    *,
    account_id: str,
    lock_owner: datetime.datetime,
    folders: list[InboxFolder],
    mailbox: str,
    batch: EmailSyncBatch,
    checkpoint: bool = True,
) -> tuple[EmailAccount, dict[str, list[str]]]:
    """Commit inbox changes and optional durable progress together, retaining pending removals."""
    with transaction.atomic():
        account = _lock_owned_account(account_id, lock_owner)
        state = dict(account.sync_cursor or {})
        mailbox_cursors = dict(state.get("mailboxes") or {})
        pending_deletions = dict(state.get("pending_deletions") or {})
        pending_deliveries = dict(state.get("pending_deliveries") or {})
        removed_ids = set(pending_deletions.get(mailbox) or [])
        if batch.reset:
            existing_items = InboxItem.objects.filter(folder__in=folders, item_type="email")
            for metadata in existing_items.values_list("raw_meta_data", flat=True):
                metadata = metadata or {}
                if metadata.get("outbound_send_pending"):
                    continue
                location = (metadata.get("locations") or {}).get(mailbox) or {}
                provider_id = location.get("provider_message_id")
                if not provider_id and metadata.get("mailbox") == mailbox:
                    provider_id = metadata.get("provider_message_id")
                if provider_id:
                    removed_ids.add(str(provider_id))
        removed_ids.update(batch.deleted_message_ids)
        removed_ids.difference_update(
            email.provider_message_id for email in batch.messages if email.mailbox == mailbox
        )
        batch_created_ids: dict[str, list[str]] = {}
        for folder in folders:
            batch_created_ids[str(folder.pk)] = []
            created_ids = set(pending_deliveries.get(str(folder.pk)) or [])
            for email in batch.messages:
                item, created = _upsert_email_inbox_item_result(email, folder)
                if created:
                    created_ids.add(str(item.pk))
                    batch_created_ids[str(folder.pk)].append(str(item.pk))
            if created_ids:
                pending_deliveries[str(folder.pk)] = sorted(created_ids)
        if batch.cursor is not None:
            mailbox_cursors[mailbox] = batch.cursor
        if mailbox_cursors:
            state["mailboxes"] = mailbox_cursors
        if removed_ids:
            pending_deletions[mailbox] = sorted(removed_ids)
        else:
            pending_deletions.pop(mailbox, None)
        if pending_deletions:
            state["pending_deletions"] = pending_deletions
        else:
            state.pop("pending_deletions", None)
        if pending_deliveries:
            state["pending_deliveries"] = pending_deliveries
        update_fields = ["sync_locked_until", "datetime_updated"]
        if checkpoint:
            account.sync_cursor = state
            update_fields.append("sync_cursor")
        account.sync_locked_until = timezone.now() + timedelta(minutes=SYNC_LOCK_MINUTES)
        account.save(update_fields=update_fields)
        return account, batch_created_ids


def _finish_email_batches(
    *,
    account_id: str,
    lock_owner: datetime.datetime,
    folders: list[InboxFolder],
    mailboxes: list[str],
    sent_mailboxes: set[str],
    transient_deliveries: dict[str, list[str]] | None = None,
) -> tuple[InboxSourceDelivery, ...]:
    """Reconcile vanished locations after moves and deliver durable new non-Sent items."""
    with transaction.atomic():
        account = _lock_owned_account(account_id, lock_owner)
        state = dict(account.sync_cursor or {})
        pending_deletions = dict(state.get("pending_deletions") or {}) if transient_deliveries is None else {}
        pending_deliveries = (
            dict(state.get("pending_deliveries") or {})
            if transient_deliveries is None else dict(transient_deliveries)
        )
        for mailbox in mailboxes:
            _remove_email_provider_locations(
                folders,
                mailbox=mailbox,
                provider_message_ids=pending_deletions.pop(mailbox, []),
            )
        deliveries = []
        for folder in folders:
            created_ids = pending_deliveries.pop(str(folder.pk), [])
            created_items = []
            for item in InboxItem.objects.filter(folder=folder, pk__in=created_ids):
                metadata = item.raw_meta_data or {}
                locations = set((metadata.get("locations") or {}).keys())
                if metadata.get("mailbox"):
                    locations.add(metadata["mailbox"])
                if not locations.intersection(sent_mailboxes):
                    created_items.append(item)
            if created_items:
                deliveries.append(InboxSourceDelivery(folder=folder, items=tuple(created_items)))
        for key, pending in (
            ("pending_deletions", pending_deletions),
            ("pending_deliveries", pending_deliveries),
        ):
            if pending:
                state[key] = pending
            else:
                state.pop(key, None)
        if transient_deliveries is None:
            account.sync_cursor = state
            account.save(update_fields=["sync_cursor", "datetime_updated"])
        return tuple(deliveries)


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
    """Exhaust provider pages, checkpoint durable changes, and suppress Sent notifications."""
    email_account = EmailAccount.objects.get(pk=email_account_id)
    if email_account.status != EmailAccount.Status.ACTIVE or not email_account.sync_enabled:
        return InboxSourceExecutionResult(outcome="skipped", reason="account_unavailable")
    now = timezone.now()
    lock_acquired = (
        EmailAccount.objects
        .filter(pk=email_account.pk, status=EmailAccount.Status.ACTIVE, sync_enabled=True)
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

    sync_error = ""
    try:
        linked_folders = list(folders)
        if _account_sync_mode(email_account) != EmailSyncMode.POLLING.value:
            result = InboxSourceExecutionResult(outcome="skipped", reason="not_polling")
        elif not linked_folders:
            result = InboxSourceExecutionResult(outcome="skipped", reason="no_linked_folders")
        else:
            mailbox_mapping = normalize_mailboxes(email_account.mailboxes or {})
            sent_mailboxes = {
                mailbox for mailbox, settings in mailbox_mapping.items()
                if settings["sent_folder"]
            }
            selected_mailboxes = list(dict.fromkeys(mailbox for mailbox in (mailboxes or []) if mailbox))
            if not selected_mailboxes:
                selected_mailboxes = list(mailbox_mapping) or [DEFAULT_MAILBOX]
            fetched_count = 0
            filtered = from_date is not None or to_date is not None
            transient_deliveries: dict[str, list[str]] | None = {} if filtered else None
            for mailbox in selected_mailboxes:
                adapter = _resolve_email_adapter_for_account(email_account)
                try:
                    while True:
                        with transaction.atomic():
                            email_account = _lock_owned_account(email_account_id, now)
                        cursor = (email_account.sync_cursor or {}).get("mailboxes", {}).get(mailbox)
                        batch_method = getattr(type(adapter), "sync_batch", None)
                        if callable(batch_method) and not filtered:
                            batch = adapter.sync_batch(
                                mailbox=mailbox, cursor=cursor, limit=limit,
                                from_date=from_date, to_date=to_date,
                            )
                        else:
                            batch = BaseEmailAdapter.sync_batch(
                                adapter, mailbox=mailbox, cursor=cursor, limit=limit,
                                from_date=from_date, to_date=to_date,
                            )
                        if batch.has_more and (batch.cursor is None or batch.cursor == cursor):
                            raise ValueError("Email provider returned another page without advancing its cursor.")
                        email_account, created_ids = _persist_email_batch(
                            account_id=email_account_id, lock_owner=now,
                            folders=linked_folders, mailbox=mailbox, batch=batch,
                            checkpoint=not filtered,
                        )
                        if transient_deliveries is not None:
                            for folder_id, item_ids in created_ids.items():
                                transient_deliveries.setdefault(folder_id, []).extend(item_ids)
                        fetched_count += len(batch.messages)
                        if not batch.has_more:
                            break
                finally:
                    close = getattr(adapter, "close", None)
                    if callable(close):
                        close()
            deliveries = _finish_email_batches(
                account_id=email_account_id, lock_owner=now, folders=linked_folders,
                mailboxes=selected_mailboxes, sent_mailboxes=sent_mailboxes,
                transient_deliveries=transient_deliveries,
            )
            result = InboxSourceExecutionResult(
                deliveries=deliveries,
                plain_text_notifications=True,
                metrics={
                    "email_account_id": str(email_account.pk),
                    "fetched_messages": fetched_count,
                    "mailboxes": len(selected_mailboxes),
                },
            )
    except _EmailSyncStopped as exc:
        result = InboxSourceExecutionResult(outcome="skipped", reason=str(exc))
    except Exception as exc:
        sync_error = str(exc)
        raise
    finally:
        email_account.refresh_from_db()
        updates: dict[str, Any] = {
            "last_sync_error": sync_error,
            "sync_locked_until": None,
            "datetime_updated": timezone.now(),
        }
        if email_account.status == EmailAccount.Status.ACTIVE and email_account.sync_enabled:
            updates["next_sync_at"] = _next_sync_at(email_account)
        if not sync_error:
            updates["last_sync_finished_at"] = timezone.now()
        EmailAccount.objects.filter(pk=email_account.pk, last_sync_started_at=now).update(**updates)
    return result


def dispatch_due_email_syncs_source(
    folders: QuerySet[InboxFolder],
    *args: Any,
    **kwargs: Any,
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
