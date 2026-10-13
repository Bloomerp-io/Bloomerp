"""Apply registered folder grouping consistently in aggregate inboxes."""

from collections import defaultdict
from typing import TYPE_CHECKING
from django.db.models import QuerySet
from bloomerp.communication.definition import InboxItemGroup

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_item import InboxItem


def group_inbox_items(
    items: list["InboxItem"], accessible_items: QuerySet["InboxItem"]
) -> list[InboxItemGroup]:
    """Delegate each source folder's items to its own optional grouping callback."""
    by_folder: dict[object, list["InboxItem"]] = defaultdict(list)
    for item in items:
        by_folder[item.folder_id].append(item)
    groups: dict[object, InboxItemGroup] = {}
    for members in by_folder.values():
        definition = members[0].folder.inbox_folder_type()
        callback = definition.on_group if not definition.is_aggregate else None
        grouped = (
            callback(members, accessible_items)
            if callback
            else [
                InboxItemGroup(item=item, related_items=[], key=str(item.pk))
                for item in members
            ]
        )
        groups.update({group.item.pk: group for group in grouped})
    return [groups[item.pk] for item in items if item.pk in groups]
