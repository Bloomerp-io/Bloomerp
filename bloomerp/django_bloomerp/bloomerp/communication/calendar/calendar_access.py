"""Resolve Inbox calendar placement and independent calendar read permissions."""

from django.db.models import Q
from django.http import Http404

from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.services.preference_services import PreferenceManager

COMMON_CALENDAR_FIELDS = {"inboxes", "all_day", "cancelled"}


def can_view_inbox_calendar(user: AbstractBloomerpUser) -> bool:
    """Allow calendar navigation whenever the user owns or shares an Inbox."""
    return accessible_inboxes(user).exists()


def resolve_calendar_inbox(user: AbstractBloomerpUser, inbox_id: int) -> Inbox:
    """Resolve an accessible preference or shared reference to its owner Inbox."""
    available = PreferenceManager(user).get_available(Inbox)
    preference = available.filter(Q(pk=inbox_id) | Q(source_object_id=inbox_id)).first()
    if preference is None:
        raise Http404("Inbox not found.")
    inbox = preference.effective_preference
    if not accessible_inboxes(user).filter(pk=inbox.pk).exists():
        raise Http404("Inbox not found.")
    return inbox
