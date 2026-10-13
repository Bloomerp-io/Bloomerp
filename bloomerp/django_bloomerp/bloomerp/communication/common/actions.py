"""Reusable inbox actions shared by built-in and extension folder definitions."""

from typing import TYPE_CHECKING
from django.http import HttpRequest, HttpResponse
from bloomerp.communication.definition import InboxActionDefinition
from bloomerp.components.communication.emails.reply_to_email import (
    email_reply_is_available,
    reply_to_email,
)
from bloomerp.utils.requests import render_message, render_page_refresh_with_message

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_item import InboxItem
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder


def mark_as_read(request: HttpRequest, item: "InboxItem") -> HttpResponse:
    """Mark the selected item read through its registered handler."""
    item.get_inbox_item_type().on_mark_as_read(item, request)
    return render_message(request, "Item marked as read", "success")


def is_unread(item: "InboxItem") -> bool:
    """Offer the read action only for unread items."""
    return not item.is_read


def delete_item(request: HttpRequest, item: "InboxItem") -> HttpResponse:
    """Delete the selected item through its registered handler."""
    item.get_inbox_item_type().on_delete(item, request)
    return render_page_refresh_with_message(
        request, "Item deleted successfully", "success"
    )


def delete_folder(request: HttpRequest, folder: "InboxFolder") -> HttpResponse:
    """Remove the selected local folder using the existing action contract."""
    folder.delete()
    return render_page_refresh_with_message(
        request, "Inbox folder deleted successfully", "success"
    )


MARK_ALL_AS_READ_ACTION = InboxActionDefinition(
    key="mark_all_as_read", name="Mark All as Read", icon="fa fa-check-double"
)
MARK_INBOX_ITEM_AS_READ_ACTION = InboxActionDefinition(
    key="mark_as_read",
    name="Mark as Read",
    icon="fa fa-check",
    http_method="post",
    execution_func=mark_as_read,
    availability_func=is_unread,
)
DELETE_INBOX_ITEM_ACTION = InboxActionDefinition(
    key="delete_inbox_item",
    name="Delete Inbox Item",
    icon="fa fa-trash",
    is_primary_action=False,
    http_method="post",
    execution_func=delete_item,
)
REPLY_TO_EMAIL_ACTION = InboxActionDefinition(
    key="reply_to_email",
    name="Reply",
    icon="fa fa-reply",
    target="render-item",
    execution_func=reply_to_email,
    availability_func=email_reply_is_available,
)
DELETE_INBOX_FOLDER_ACTION = InboxActionDefinition(
    key="delete_inbox_folder",
    name="Delete Inbox Folder",
    icon="fa fa-trash",
    is_primary_action=False,
    execution_func=delete_folder,
)
