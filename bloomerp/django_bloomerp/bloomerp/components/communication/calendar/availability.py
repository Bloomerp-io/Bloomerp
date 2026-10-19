"""Permission-scoped free/busy data for the event composer."""

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET

from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router


@router.register(
    path="components/communication/calendar/availability/",
    url_name="components_calendar_availability",
)
@login_required
@require_GET
def availability(request: HttpRequest) -> HttpResponse:
    """Return private free/busy intervals for readable users in one bounded day."""
    try:
        day = forms.DateField().clean(request.GET.get("day"))
        zone = ZoneInfo(
            request.GET.get("timezone") or timezone.get_current_timezone_name()
        )
        identifiers = list(
            dict.fromkeys([str(request.user.pk), *request.GET.getlist("users")])
        )
        if len(identifiers) > 100:
            raise ValueError
        result = calendar_availability(request.user, identifiers, day, zone)
    except (ValidationError, ValueError, ZoneInfoNotFoundError):
        return JsonResponse({"error": _("Invalid availability request.")}, status=400)
    response = JsonResponse({"users": result})
    response["Cache-Control"] = "private, no-store"
    return response


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
