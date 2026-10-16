"""Permission-scoped free/busy data for the event composer."""

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db.models import Q

from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager


def calendar_availability(
    actor: AbstractBloomerpUser,
    identifiers: list[str],
    day: date,
    zone: ZoneInfo,
) -> list[dict[str, Any]]:
    """Authorize people first, then expose only busy intervals across their accessible inboxes."""
    manager = UserPolicyManager(actor)
    model = get_user_model()
    users = (
        manager.get_accessible_queryset(model, "view").filter(
            pk__in=identifiers, is_active=True
        )
        if manager.has_global_permission(model, "view")
        else model.objects.none()
    )
    users = model.objects.filter(
        Q(pk__in=users.values("pk")) | Q(pk=actor.pk),
        is_active=True,
    )
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    results: list[dict[str, Any]] = []
    for person in users:
        inboxes = accessible_inboxes(person)
        result: dict[str, Any] = {
            "id": str(person.pk),
            "label": str(person),
            "available": False,
            "busy": [],
        }
        results.append(result)
        if not inboxes.exists():
            continue
        events = (
            CalendarEvent.objects.filter(inboxes__in=inboxes, cancelled=False)
            .filter(
                Q(start__lt=end, end__gt=start)
                | Q(start_date__lte=day, end_date__gt=day),
            )
            .distinct()
        )
        result["available"] = True
        for event in events:
            result["busy"].append(
                {
                    "start": max(
                        start,
                        datetime.combine(event.start_date, time.min, tzinfo=zone)
                        if event.all_day
                        else event.start,
                    ).isoformat(),
                    "end": min(
                        end,
                        datetime.combine(event.end_date, time.min, tzinfo=zone)
                        if event.all_day
                        else event.end,
                    ).isoformat(),
                }
            )
    return results
