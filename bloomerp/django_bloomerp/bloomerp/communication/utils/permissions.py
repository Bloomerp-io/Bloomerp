from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q, QuerySet

from bloomerp.models.users.user import AbstractBloomerpUser

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox import Inbox
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.communication.inbox.inbox_item import InboxItem


def accessible_inboxes(user: AbstractBloomerpUser) -> QuerySet[Inbox]:
    """Return effective inbox sources currently available to ``user``."""
    from bloomerp.models.communication.inbox.inbox import Inbox

    return (
        Inbox.objects.filter(source_object__isnull=True)
        .filter(
            Q(user=user) | Q(shared_with_users=user) | Q(shared_with_groups__user=user)
        )
        .distinct()
    )


def manageable_inboxes(user: AbstractBloomerpUser) -> QuerySet[Inbox]:
    """Return source inboxes whose configuration ``user`` owns."""
    from bloomerp.models.communication.inbox.inbox import Inbox

    return Inbox.objects.filter(user=user, source_object__isnull=True)


def accessible_inbox_folders(
    user: AbstractBloomerpUser,
) -> QuerySet[InboxFolder]:
    """Return folders belonging to inbox sources available to ``user``."""
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder

    return InboxFolder.objects.filter(inbox__in=accessible_inboxes(user))


def accessible_inbox_items(user: AbstractBloomerpUser) -> QuerySet[InboxItem]:
    """Return items belonging to inbox sources available to ``user``."""
    from bloomerp.communication.builtins.instant_messaging.access import IMAccessManager
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

    conversation_ids = [
        str(pk)
        for pk in IMAccessManager(user).get_conversations().values_list("pk", flat=True)
    ]
    return InboxItem.objects.filter(folder__inbox__in=accessible_inboxes(user)).filter(
        ~Q(item_type="instant_messaging_item")
        | Q(related_item_id__in=conversation_ids, folder__inbox__user=user)
    )


def user_has_access_to_inbox_folder(
    user: AbstractBloomerpUser,
    inbox_folder: InboxFolder,
) -> bool:
    """Return whether ``user`` can access ``inbox_folder``."""
    return accessible_inbox_folders(user).filter(pk=inbox_folder.pk).exists()
