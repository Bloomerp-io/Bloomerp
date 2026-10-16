"""Store inbox-specific overlay choices without granting access through saved preferences."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import QuerySet

from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.preference_services import PreferenceManager

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox import Inbox


def readable_overlay_users(
    actor: AbstractBloomerpUser, identifiers: list[str]
) -> list[str]:
    """Recheck active user row access before retaining or exposing overlay selections."""
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
) -> QuerySet[Inbox]:
    """Resolve selected readable users to inbox IDs for the ordinary calendar membership filter."""
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


def save_calendar_overlay_selection(
    actor: AbstractBloomerpUser, inbox_id: int, selection: dict[str, list[str]]
) -> None:
    """Persist private overlay choices on the actor's selected preference, never its shared source."""
    content_type = ContentType.objects.get_for_model(CalendarEvent)
    PreferenceManager(actor).get_or_create_selected(
        UserListViewPreference, {"content_type_id": content_type.pk}
    )
    with transaction.atomic():
        preference = UserListViewPreference.objects.select_for_update().get(
            user=actor, content_type=content_type, selected=True
        )
        options: dict[str, Any] = dict(preference.options)
        overlays = dict(options.get("inbox_calendar_overlays", {}))
        overlays[str(inbox_id)] = {
            **selection,
            "calendar_inboxes": [
                str(pk)
                for pk in calendar_overlay_inboxes(actor, selection).values_list(
                    "pk", flat=True
                )
            ],
        }
        options["inbox_calendar_overlays"] = overlays
        preference.options = options
        preference.save(update_fields=["options"])
