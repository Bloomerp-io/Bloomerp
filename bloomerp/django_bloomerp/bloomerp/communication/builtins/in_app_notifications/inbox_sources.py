from django.db.models import Q

from bloomerp.communication.builtins.in_app_notifications.base import SystemMessage


def resolve_system_message_folders(
    *,
    user_ids: list[int | str],
    **kwargs,
):
    from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder

    return InboxFolder.objects.filter(
        Q(inbox__user_id__in=user_ids)
        | Q(inbox__shared_with_users__id__in=user_ids)
        | Q(inbox__shared_with_groups__user__id__in=user_ids),
        inbox__source_object__isnull=True,
        type=INBOX_FOLDER_REGISTRY.IN_APP_NOTIFICATIONS.key,
    ).distinct()


def handle_system_message(
    folders,
    *,
    system_message_type: str,
    data: dict,
    **kwargs,
):
    from bloomerp.communication.inbox_sources import (
        InboxSourceDelivery,
        InboxSourceExecutionResult,
    )

    deliveries = []
    for folder in folders:
        item = SystemMessage.create_item(
            message_type=system_message_type,
            folder=folder,
            data=data,
        )
        deliveries.append(InboxSourceDelivery(folder=folder, items=(item,)))
    return InboxSourceExecutionResult(deliveries=tuple(deliveries))
