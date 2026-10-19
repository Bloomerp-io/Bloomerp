"""Bridge secured calendar actions to existing email and event detail screens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models

from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox import Inbox
    from bloomerp.models.communication.inbox.inbox_item import InboxItem


def invitation_context(
    item: InboxItem, user: AbstractBloomerpUser
) -> dict[str, Any] | None:
    """Render only an invited account's policy-readable current meeting and response."""
    from bloomerp.models.communication.calendar import CalendarEvent
    from bloomerp.models.communication.email_account import EmailAccount

    from .outgoing import require_event_access

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


def can_view_inbox_calendar(user: AbstractBloomerpUser) -> bool:
    """Allow calendar navigation whenever the user owns or shares an Inbox."""
    from bloomerp.communication.utils.permissions import accessible_inboxes

    return accessible_inboxes(user).exists()


def resolve_calendar_inbox(user: AbstractBloomerpUser, inbox_id: int) -> "Inbox":
    """Resolve an accessible preference or shared reference to its owner Inbox."""
    from django.db.models import Q
    from django.http import Http404

    from bloomerp.communication.utils.permissions import accessible_inboxes
    from bloomerp.models.communication.inbox.inbox import Inbox
    from bloomerp.services.preference_services import PreferenceManager

    available = PreferenceManager(user).get_available(Inbox)
    preference = available.filter(Q(pk=inbox_id) | Q(source_object_id=inbox_id)).first()
    if preference is None:
        raise Http404("Inbox not found.")
    inbox = preference.effective_preference
    if not accessible_inboxes(user).filter(pk=inbox.pk).exists():
        raise Http404("Inbox not found.")
    return inbox


def readable_overlay_users(
    actor: AbstractBloomerpUser, identifiers: list[str]
) -> list[str]:
    """Recheck active user row access before retaining or exposing overlay selections."""
    from django.contrib.auth import get_user_model

    model = get_user_model()
    manager = UserPolicyManager(actor)
    if not manager.has_global_permission(model, "view"):
        return []
    return [
        str(pk)
        for pk in manager.get_accessible_queryset(model, "view")
        .filter(pk__in=identifiers, is_active=True)
        .values_list("pk", flat=True)
    ]


def calendar_overlay_selection(
    actor: AbstractBloomerpUser, inbox_id: int
) -> dict[str, list[str]]:
    """Restore this inbox's selection and discard calendars or users no longer accessible."""
    from django.contrib.contenttypes.models import ContentType

    from bloomerp.communication.utils.permissions import accessible_inboxes
    from bloomerp.models.communication.calendar import CalendarEvent
    from bloomerp.models.users.user_list_view_preference import UserListViewPreference

    content_type = ContentType.objects.get_for_model(CalendarEvent)
    preference = UserListViewPreference.objects.filter(
        user=actor, content_type=content_type, selected=True
    ).first()
    saved = (
        preference.options.get("inbox_calendar_overlays", {}).get(str(inbox_id), {})
        if preference
        else {}
    )
    available = {
        str(pk) for pk in accessible_inboxes(actor).values_list("pk", flat=True)
    }
    return {
        "inboxes": [
            value
            for value in saved.get("inboxes", [str(inbox_id)])
            if value in available
        ],
        "users": readable_overlay_users(actor, saved.get("users", [])),
    }


def calendar_overlay_inboxes(
    actor: AbstractBloomerpUser, selection: dict[str, list[str]]
) -> "models.QuerySet[Inbox]":
    """Resolve selected readable users to inbox IDs for the ordinary calendar membership filter."""
    from django.contrib.auth import get_user_model

    from bloomerp.communication.utils.permissions import accessible_inboxes
    from bloomerp.models.communication.inbox.inbox import Inbox

    identifiers = set(
        accessible_inboxes(actor)
        .filter(pk__in=selection["inboxes"])
        .values_list("pk", flat=True)
    )
    people = get_user_model().objects.filter(
        pk__in=readable_overlay_users(actor, selection["users"])
    )
    for person in people:
        identifiers.update(accessible_inboxes(person).values_list("pk", flat=True))
    return Inbox.objects.filter(pk__in=identifiers)


def issue_calendar_token(
    user: AbstractBloomerpUser, inbox_id: int, selected: list[str]
) -> str:
    """Delegate event reads for validated overlay inboxes and writes for the current inbox only."""
    from datetime import timedelta

    from django.utils import timezone

    from bloomerp.filters.definition import FilterCondition
    from bloomerp.models.communication.calendar import CalendarEvent
    from bloomerp.permissions.definition import (
        AccessRule,
        BloomerpPermission,
        PermissionToken,
        RowPolicyRuleContent,
    )

    # This endpoint delegates only after resolve_calendar_inbox checks ownership/sharing.
    view_condition = FilterCondition(
        field_path="inboxes", lookup_id="values_in", value=selected or ["0"]
    )
    fields = {
        "id",
        "title",
        "content",
        "location",
        "start",
        "end",
        "start_date",
        "end_date",
        "event_timezone",
        "all_day",
        "cancelled",
        "inboxes",
        "organizing_inbox",
        "organizer_email",
    }
    token = PermissionToken(
        model_label=CalendarEvent._meta.label_lower,
        audience=str(user.pk),
        expiry=timezone.now() + timedelta(hours=1),
        rule=AccessRule(
            row_permissions=[
                RowPolicyRuleContent(
                    conditions=[view_condition],
                    permissions=[
                        BloomerpPermission.VIEW,
                    ],
                ),
                RowPolicyRuleContent(
                    conditions=[
                        FilterCondition(
                            field_path="organizing_inbox",
                            lookup_id="equals",
                            value=str(inbox_id),
                        )
                    ],
                    permissions=[BloomerpPermission.ADD, BloomerpPermission.CHANGE],
                ),
            ],
            field_permissions={
                field: [
                    BloomerpPermission.VIEW,
                    BloomerpPermission.ADD,
                    BloomerpPermission.CHANGE,
                ]
                for field in fields
            },
        ),
    ).sign()
    return token
