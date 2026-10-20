"""Durable, recipient-scoped notifications for newly introduced mentions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import QuerySet
from django.http import HttpRequest
from django.template.loader import render_to_string

from bloomerp.communication.builtins.in_app_notifications.base import (
    BaseSystemMessageType,
    SystemMessageItemData,
)
from bloomerp.communication.inbox_sources import (
    InboxSourceDelivery,
    InboxSourceExecutionResult,
)

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.communication.inbox.inbox_item import InboxItem


class MentionSystemMessage(BaseSystemMessageType):
    """Render a small snapshot without reading protected object or field contents."""

    @classmethod
    def build_item_data(cls, data: dict[str, Any]) -> SystemMessageItemData:
        """Store the actor, object label and optional field name at mention time."""
        suffix = f" ({data['field_label']})" if data.get("field_label") else ""
        message = (
            f"{data['actor_label']} mentioned you in {data['object_label']}{suffix}."
        )
        return SystemMessageItemData(
            title="You were mentioned",
            snippet=message,
            raw_meta_data=data,
        )

    @classmethod
    def render(cls, item: InboxItem, request: HttpRequest | None = None) -> str:
        """Escape snapshot text and link only to an instance-local permission gate."""
        url = str((item.raw_meta_data or {}).get("url") or "")
        if (
            not url.startswith("/")
            or url.startswith("//")
            or "\\" in url
            or any(ord(char) < 32 for char in url)
        ):
            url = ""
        return render_to_string(
            "inbox_items/mention.html", {"item": item, "url": url}, request=request
        )


def resolve_mention_folders(
    *, mentions: list[dict[str, Any]], **kwargs: Any
) -> QuerySet[InboxFolder]:
    """Target recipients' owned inboxes, never inboxes merely shared with them."""
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder

    return InboxFolder.objects.filter(
        inbox__user_id__in={entry["user_id"] for entry in mentions},
        inbox__source_object__isnull=True,
        type="in_app_notifications",
    ).select_related("inbox")


def handle_mentions(
    folders: QuerySet[InboxFolder], *, mentions: list[dict[str, Any]], **kwargs: Any
) -> InboxSourceExecutionResult:
    """Persist each new user/field scope through the existing notification system."""
    from bloomerp.communication.builtins.in_app_notifications.base import SystemMessage

    by_user: dict[str, list[dict[str, Any]]] = {}
    for entry in mentions:
        by_user.setdefault(str(entry["user_id"]), []).append(entry)
    deliveries = []
    for folder in folders:
        items = tuple(
            SystemMessage.create_item(message_type="mention", folder=folder, data=data)
            for data in by_user.get(str(folder.inbox.user_id), [])
        )
        if items:
            deliveries.append(InboxSourceDelivery(folder=folder, items=items))
    return InboxSourceExecutionResult(
        deliveries=tuple(deliveries),
        defer_notifications_until_commit=True,
        plain_text_notifications=True,
    )
