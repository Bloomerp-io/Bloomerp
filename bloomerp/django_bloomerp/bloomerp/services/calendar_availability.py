"""Permission-scoped free/busy data for the event composer."""

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db.models import Q

from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager


def calendar_availability(
    actor: AbstractBloomerpUser, identifiers: list[str], day: date, zone: ZoneInfo
) -> list[dict[str, Any]]:
    """Return busy intervals only for readable calendars, explicitly marking incomplete access."""
    manager = UserPolicyManager(actor)
    model = get_user_model()
    users = (
        manager.get_accessible_queryset(model, "view").filter(
            pk__in=identifiers, is_active=True
        )
        if manager.has_global_permission(model, "view")
        else model.objects.none()
    )
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    results: list[dict[str, Any]] = []
    for person in users:
        selected = Inbox.objects.filter(user=person, selected=True).first()
        inbox = selected.effective_preference if selected else None
        result: dict[str, Any] = {
            "id": str(person.pk),
            "label": str(person),
            "available": False,
            "busy": [],
        }
        results.append(result)
        if (
            inbox is None
            or not accessible_inboxes(actor).filter(pk=inbox.pk).exists()
            or not manager.has_global_permission(CalendarEvent, "view")
        ):
            continue
        events = (
            CalendarEvent.objects.filter(inboxes=inbox, cancelled=False)
            .filter(
                Q(start__lt=end, end__gt=start)
                | Q(start_date__lte=day, end_date__gt=day),
            )
            .distinct()
        )
        readable = manager.get_accessible_queryset(CalendarEvent, "view")
        fields = [
            "start",
            "end",
            "start_date",
            "end_date",
            "all_day",
            "cancelled",
            "inboxes",
        ]
        if events.exclude(pk__in=readable).exists() or any(
            not manager.has_access_to_object(event, "view", fields=fields)
            for event in events
        ):
            continue
        result["available"] = True
        for event in events:
            result["busy"].append(
                {
                    "start": (start if event.all_day else event.start).isoformat(),
                    "end": (end if event.all_day else event.end).isoformat(),
                }
            )
    return results
