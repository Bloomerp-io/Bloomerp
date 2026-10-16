"""Bridge secured calendar actions to existing email and event detail screens."""

from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.http import HttpRequest
from django.urls import reverse

from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager

from .outgoing import require_event_access


def scheduling_action_url(event: models.Model) -> str:
    """Resolve the modal endpoint for an existing calendar event."""
    return reverse("components_calendar_schedule", kwargs={"event_id": event.pk})


def can_schedule_event(request: HttpRequest, event: models.Model) -> bool:
    """Show the organizer action only when event read and scheduling writes are allowed."""
    if not isinstance(event, CalendarEvent) or not event.organizing_inbox_id:
        return False
    try:
        require_event_access(
            request.user,
            event,
            write_fields=[
                "sequence",
                "scheduling_dtstamp",
                "cancelled",
                "invitation_sent_at",
            ],
        )
    except PermissionDenied:
        return False
    return True


def invitation_context(
    item: InboxItem, user: AbstractBloomerpUser
) -> dict[str, Any] | None:
    """Render only an invited account's policy-readable current meeting and response."""
    records = (item.raw_meta_data or {}).get("calendar_processing", [])
    record = next(
        (
            value
            for value in records
            if value.get("method") == "REQUEST" and value.get("event_id")
        ),
        None,
    )
    if record is None:
        return None
    try:
        event_id = UUID(record["event_id"])
        event = CalendarEvent.objects.get(
            pk=event_id, inboxes=item.folder.inbox.effective_preference
        )
        require_event_access(user, event)
        account = EmailAccount.objects.get(pk=item.folder.related_object_id)
    except (
        ValueError,
        PermissionDenied,
        ValidationError,
        CalendarEvent.DoesNotExist,
        EmailAccount.DoesNotExist,
    ):
        return None
    participant = event.participants.filter(email__iexact=account.email_address).first()
    manager = UserPolicyManager(user)
    if participant is None or not manager.has_access_to_object(
        participant, "view", fields=["response_status", "invitation_cancelled"]
    ):
        return None
    can_respond = (
        not event.cancelled
        and not participant.invitation_cancelled
        and manager.has_access_to_object(
            participant,
            "change",
            fields=[
                "response_status",
                "responded_at",
                "reply_sequence",
                "reply_dtstamp",
                "last_sent_reply_sequence",
                "last_sent_reply_status",
            ],
        )
    )
    return {
        "event": event,
        "participant": participant,
        "can_respond": can_respond,
        "item_id": item.pk,
    }
