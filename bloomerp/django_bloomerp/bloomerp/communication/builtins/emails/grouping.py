"""Find related local email indexes without fetching bodies or crossing accounts."""

from collections import defaultdict
from typing import TYPE_CHECKING
import re
from uuid import UUID

from django.db.models import Q, QuerySet
from bloomerp.communication.definition import InboxItemGroup

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_item import InboxItem


def message_ids(item: "InboxItem") -> set[str]:
    """Extract RFC message identities and threading references, never subject guesses."""
    metadata = item.raw_meta_data or {}
    values = [
        metadata.get("message_id"),
        metadata.get("in_reply_to"),
        item.related_item_id,
    ]
    references = metadata.get("references") or []
    values.extend(references if isinstance(references, list) else [references])
    identifiers = {
        identifier
        for value in values
        if isinstance(value, str)
        for identifier in re.findall(r"<[^<>]+>", value)
    }
    identifiers.add(f"local:{item.pk}")
    for field in ("conversation_id", "parent_item_id"):
        if metadata.get(field):
            identifiers.add(f"local:{metadata[field]}")
    return identifiers


def group_email_items(
    items: list["InboxItem"], accessible_items: QuerySet["InboxItem"]
) -> list[InboxItemGroup]:
    """Expand header-linked conversations across mailboxes within each accessible folder.

    Only local indexes are queried. Each frontier uses a batch query, and visited
    records stop cycles. Missing headers leave independent messages ungrouped.
    """
    indexed = {item.pk: item for item in items}
    frontier: dict[object, set[str]] = defaultdict(set)
    searched: dict[object, set[str]] = defaultdict(set)
    for item in items:
        if item.item_type == "email":
            frontier[item.folder_id].update(message_ids(item))
    while any(frontier.values()):
        query = Q(pk__in=[])
        for folder_id, identifiers in frontier.items():
            local_ids = [
                value.removeprefix("local:")
                for value in identifiers
                if value.startswith("local:")
            ]
            primary_keys = []
            for value in local_ids:
                try:
                    primary_keys.append(UUID(value))
                except ValueError:
                    continue
            query |= Q(folder_id=folder_id) & (
                Q(pk__in=primary_keys)
                | Q(raw_meta_data__conversation_id__in=local_ids)
                | Q(raw_meta_data__parent_item_id__in=local_ids)
                | Q(raw_meta_data__message_id__in=list(identifiers))
                | Q(related_item_id__in=list(identifiers))
                | Q(raw_meta_data__in_reply_to__in=list(identifiers))
                | Q(raw_meta_data__references__0__in=list(identifiers))
            )
            searched[folder_id].update(identifiers)
        frontier = defaultdict(set)
        for item in accessible_items.filter(query, item_type="email").select_related(
            "folder"
        ):
            if item.pk in indexed:
                continue
            indexed[item.pk] = item
            frontier[item.folder_id].update(
                message_ids(item) - searched[item.folder_id]
            )

    parents: dict[object, object] = {pk: pk for pk in indexed}

    def root(key: object) -> object:
        """Resolve and compress a conversation's disjoint-set representative."""
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    owners: dict[tuple[object, str], object] = {}
    for item in indexed.values():
        if item.item_type != "email":
            continue
        for identifier in message_ids(item):
            key = (item.folder_id, identifier)
            if key in owners:
                parents[root(item.pk)] = root(owners[key])
            else:
                owners[key] = item.pk
    members: dict[object, list["InboxItem"]] = defaultdict(list)
    for item in indexed.values():
        members[root(item.pk)].append(item)
    groups = []
    emitted = set()
    for item in items:
        key = root(item.pk)
        if key in emitted:
            continue
        emitted.add(key)
        conversation = members[key]
        related = sorted(
            (other for other in conversation if other.pk != item.pk), key=item_sort_key
        )
        groups.append(
            InboxItemGroup(
                item=item,
                related_items=related,
                key=min(str(other.pk) for other in conversation),
            )
        )
    return groups


def item_sort_key(item: "InboxItem") -> tuple[str, str]:
    """Keep expanded messages in stable chronological order."""
    received = item.datetime_received or item.datetime_created
    return (received.isoformat() if received else "", str(item.pk))
