"""Project conversation activity into the existing personal inbox source pipeline."""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest

if TYPE_CHECKING:
    from bloomerp.communication.inbox_sources import InboxSourceExecutionResult
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.communication.inbox.inbox_item import InboxItem


def render_inbox_conversation(item: "InboxItem", request: HttpRequest) -> str:
    """Reuse the permission-checked conversation fragment, editor and live updates."""
    from bloomerp.components.communication.instant_messaging.conversation import (
        render_conversation,
    )

    return render_conversation(request, UUID(item.related_item_id)).content.decode()


def resolve_conversation_folders(
    *, conversation_id: str, **kwargs: Any
) -> QuerySet["InboxFolder"]:
    """Deliver to participant-owned personal folders, never shared inbox audiences."""
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.communication.instant_messaging import (
        IMConversationParticipant,
    )

    users = IMConversationParticipant.objects.filter(
        conversation_id=conversation_id, left_at__isnull=True, user__is_active=True
    ).values("user_id")
    return InboxFolder.objects.filter(
        type="instant_messaging",
        inbox__user_id__in=users,
        inbox__source_object__isnull=True,
        inbox__shared_with_users__isnull=True,
        inbox__shared_with_groups__isnull=True,
    )


@transaction.atomic
def handle_conversation_activity(
    folders: QuerySet["InboxFolder"],
    *,
    conversation_id: str,
    notify: bool = True,
    **kwargs: Any,
) -> "InboxSourceExecutionResult":
    """Upsert one item per folder under the conversation lock using latest activity."""
    from bloomerp.communication.inbox_sources import (
        InboxSourceDelivery,
        InboxSourceExecutionResult,
    )
    from bloomerp.models.communication.inbox.inbox_item import InboxItem
    from bloomerp.models.communication.instant_messaging import IMConversation

    from .presentation import conversation_identity, participant_label

    chat = IMConversation.objects.select_for_update().filter(pk=conversation_id).first()
    if chat is None:
        return InboxSourceExecutionResult(
            outcome="skipped", reason="Conversation removed"
        )
    latest = (
        chat.messages.filter(deleted_at__isnull=True)
        .select_related("sender__user", "sender__identity")
        .order_by("-sequence")
        .first()
    )
    activity = chat.activities.order_by("-datetime_updated").first()
    if latest is None and activity is None:
        return InboxSourceExecutionResult(outcome="skipped", reason="No activity")
    deliveries = []
    for folder in folders.select_related("inbox"):
        member = chat.participants.select_related("last_read_message").get(
            user_id=folder.inbox.user_id, left_at__isnull=True
        )
        from .access import IMAccessManager

        if not IMAccessManager(member.user).has_access_to_conversation(chat):
            continue
        unread = (
            chat.messages.filter(
                deleted_at__isnull=True,
                thread_root__isnull=True,
                sequence__gt=member.last_read_message.sequence
                if member.last_read_message
                else 0,
            )
            .exclude(sender=member)
            .exists()
        )
        unread_activity = chat.activities.exclude(actor=member.user)
        if member.last_read_activity_at:
            unread_activity = unread_activity.filter(
                datetime_updated__gt=member.last_read_activity_at
            )
        unread = unread or unread_activity.exists()
        use_activity = activity is not None and (
            latest is None or activity.datetime_updated > latest.datetime_created
        )
        item, _ = InboxItem.objects.update_or_create(
            folder=folder,
            item_type="instant_messaging_item",
            related_item_id=str(chat.pk),
            defaults={
                "title": conversation_identity(chat, member.user_id)["displayName"][
                    :1000
                ],
                "actor": "" if use_activity else participant_label(latest.sender)[:255],
                "snippet": activity.summary if use_activity else latest.body[:500],
                "datetime_received": activity.datetime_updated
                if use_activity
                else latest.sent_at or latest.datetime_created,
                "is_read": not unread,
            },
        )
        if (
            notify
            and unread
            and (use_activity or latest.sender.user_id != member.user_id)
        ):
            deliveries.append(InboxSourceDelivery(folder=folder, items=(item,)))
    return InboxSourceExecutionResult(deliveries=tuple(deliveries))


def publish_conversation_activity(
    conversation_id: UUID, *, notify: bool = True
) -> None:
    """Dispatch conversation updates through the registered inbox event source."""
    from bloomerp.communication.inbox_sources import publish_event

    publish_event(
        "im.conversation.activity", conversation_id=str(conversation_id), notify=notify
    )


def sync_conversation_read(conversation_id: UUID, user_id: int) -> None:
    """Synchronize personal inbox flags with the existing root-message read position."""
    from bloomerp.models.communication.inbox.inbox_item import InboxItem
    from bloomerp.models.communication.instant_messaging import (
        IMConversationParticipant,
    )

    member = IMConversationParticipant.objects.select_related("last_read_message").get(
        conversation_id=conversation_id, user_id=user_id, left_at__isnull=True
    )
    unread = (
        member.conversation.messages.filter(
            deleted_at__isnull=True,
            thread_root__isnull=True,
            sequence__gt=member.last_read_message.sequence
            if member.last_read_message
            else 0,
        )
        .exclude(sender=member)
        .exists()
    )
    activities = member.conversation.activities.exclude(actor=user_id)
    if member.last_read_activity_at:
        activities = activities.filter(
            datetime_updated__gt=member.last_read_activity_at
        )
    unread = unread or activities.exists()
    InboxItem.objects.filter(
        item_type="instant_messaging_item",
        related_item_id=str(conversation_id),
        folder__inbox__user_id=user_id,
    ).update(is_read=not unread)
