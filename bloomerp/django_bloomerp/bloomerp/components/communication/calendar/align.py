"""Save alignment preferences and reload the shared calendar dataview."""

import json
from typing import Any

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from bloomerp.communication.calendar.access import (
    calendar_overlay_inboxes,
    readable_overlay_users,
    resolve_calendar_inbox,
)
from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager


@router.register(
    path="components/communication/calendar/<int:inbox_id>/align/",
    url_name="components_calendar_align",
)
@login_required
@require_POST
def align_calendars(request: HttpRequest, inbox_id: int) -> HttpResponse:
    """Save the calendar selection and return its authorized dataview loader with filters hidden."""
    inbox = resolve_calendar_inbox(request.user, inbox_id)
    try:
        data = json.loads(
            request.body
            if request.content_type == "application/json"
            else request.POST.get("selection", "")
        )
        selected = data["inboxes"]
        users = data["users"]
        if (
            not isinstance(selected, list)
            or not isinstance(users, list)
            or len(selected) > 100
            or len(users) > 100
            or not all(isinstance(value, str) for value in [*selected, *users])
        ):
            raise ValueError
        allowed = {
            str(pk)
            for pk in accessible_inboxes(request.user).values_list("pk", flat=True)
        }
        readable = readable_overlay_users(request.user, users)
        if not set(selected) <= allowed or set(users) != set(readable):
            return JsonResponse(
                {"error": _("Calendar selection is no longer accessible.")},
                status=403,
            )
        if not selected and not users:
            raise ValueError
    except (ValueError, KeyError, TypeError, ValidationError):
        return JsonResponse({"error": _("Invalid calendar selection.")}, status=400)
    selection = {"inboxes": list(dict.fromkeys(selected)), "users": readable}
    content_type = ContentType.objects.get_for_model(CalendarEvent)
    PreferenceManager(request.user).get_or_create_selected(
        UserListViewPreference, {"content_type_id": content_type.pk}
    )
    with transaction.atomic():
        preference = UserListViewPreference.objects.select_for_update().get(
            user=request.user, content_type=content_type, selected=True
        )
        options: dict[str, Any] = dict(preference.options)
        overlays = dict(options.get("inbox_calendar_overlays", {}))
        overlays[str(inbox.pk)] = {
            **selection,
            "calendar_inboxes": [
                str(pk)
                for pk in calendar_overlay_inboxes(request.user, selection).values_list(
                    "pk", flat=True
                )
            ],
        }
        options["inbox_calendar_overlays"] = overlays
        preference.options = options
        preference.save(update_fields=["options"])

    from bloomerp.views.communication.calendar.inbox_calendar import (
        inbox_calendar_context,
    )

    context = inbox_calendar_context(request, inbox.pk)
    return render(request, "cotton/features/dataviews/call.html", {
        "content_type_id": context["calendar_content_type_id"],
        "filters": context["calendar_filters"],
        "args": context["calendar_args"],
        "token": context["calendar_token"],
        "hide_filters": True,
        "sync_url": request.headers.get("X-Bloomerp-Sync-Url", "false").lower() == "true",
    })
