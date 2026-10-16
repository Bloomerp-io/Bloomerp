"""Resolve Inbox calendar placement and independent calendar read permissions."""

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404

from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.preference_services import PreferenceManager

COMMON_CALENDAR_FIELDS = {"inboxes", "all_day", "cancelled"}


def can_view_inbox_calendar(user: AbstractBloomerpUser) -> bool:
    """Require event access and at least one readable date representation."""
    manager = UserPolicyManager(user)
    if not manager.has_global_permission(CalendarEvent, "view"):
        return False
    fields = set(
        manager.get_accessible_fields(CalendarEvent, "view").values_list(
            "field", flat=True
        )
    )
    return COMMON_CALENDAR_FIELDS.issubset(fields) and (
        {"start", "end"}.issubset(fields) or {"start_date", "end_date"}.issubset(fields)
    )


def resolve_calendar_inbox(user: AbstractBloomerpUser, inbox_id: int) -> Inbox:
    """Resolve an accessible preference or shared reference to its owner Inbox."""
    available = PreferenceManager(user).get_available(Inbox)
    preference = available.filter(Q(pk=inbox_id) | Q(source_object_id=inbox_id)).first()
    if preference is None:
        raise Http404("Inbox not found.")
    inbox = preference.effective_preference
    if not accessible_inboxes(user).filter(pk=inbox.pk).exists():
        raise Http404("Inbox not found.")
    if not can_view_inbox_calendar(user):
        raise PermissionDenied(
            "You do not have permission to view calendar events and their dates."
        )
    return inbox
