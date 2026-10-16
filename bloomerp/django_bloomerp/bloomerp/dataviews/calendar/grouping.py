"""Reusable stable colors and permission-scoped relation groups for calendars."""

from django.db.models import Model, QuerySet

from bloomerp.models.users.base_preference import BasePreference
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.preference_services import PreferenceManager

CALENDAR_COLORS = (
    "bg-primary-100 text-primary-800 border-primary-200",
    "bg-secondary-100 text-secondary-800 border-secondary-200",
    "bg-success-light text-success-dark border-success-light",
    "bg-warning-light text-warning-dark border-warning-light",
    "bg-danger-light text-danger-dark border-danger-light",
    "bg-base text-dark border-gray-200",
)


def calendar_group_color(value: str, *, relation: bool = False) -> str:
    """Keep colors stable across filtering and paging, using relation IDs rather than mutable names."""
    if relation and value.isdecimal():
        index = int(value)
    else:
        index = sum(
            (position + 1) * ord(character) for position, character in enumerate(value)
        )
    return CALENDAR_COLORS[index % len(CALENDAR_COLORS)]


def readable_calendar_groups(
    user: AbstractBloomerpUser, model: type[Model]
) -> QuerySet:
    """Scope relation labels through the model's normal policy or preference-sharing authority."""
    if issubclass(model, BasePreference):
        available = PreferenceManager(user).get_available(model)
        identifiers = {item.source_object_id or item.pk for item in available}
        if model._meta.label_lower == "bloomerp.inbox":
            from bloomerp.communication.calendar.calendar_access import (
                resolve_calendar_inbox,
            )
            from bloomerp.middleware import current_request
            from bloomerp.services.calendar_overlays import (
                calendar_overlay_inboxes,
                calendar_overlay_selection,
            )

            request = current_request()
            inbox_id = request.GET.get("calendar_inbox", "") if request else ""
            if inbox_id.isdigit():
                inbox = resolve_calendar_inbox(user, int(inbox_id))
                selection = calendar_overlay_selection(user, inbox.pk)
                identifiers.update(
                    calendar_overlay_inboxes(user, selection).values_list(
                        "pk", flat=True
                    )
                )
        return model.objects.filter(pk__in=identifiers)
    manager = UserPolicyManager(user)
    if not manager.has_global_permission(model, "view"):
        return model.objects.none()
    return manager.get_accessible_queryset(model, "view")
