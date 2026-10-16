"""Show the selected Inbox's shared calendar using the standard dataview grid."""

import json
from datetime import timedelta
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from bloomerp.communication.calendar.calendar_access import resolve_calendar_inbox
from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.filters.definition import FilterCondition
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    PermissionToken,
    RowPolicyRuleContent,
)
from bloomerp.router import router
from bloomerp.services.calendar_overlays import (
    calendar_overlay_inboxes,
    calendar_overlay_selection,
    readable_overlay_users,
    save_calendar_overlay_selection,
)
from bloomerp.views.base import BaseBloomerpView


@router.register(
    path="/inbox/<int:inbox_id>/calendar/",
    route_type="app",
    url_name="inbox_calendar",
    name="Inbox calendar",
)
class InboxCalendarView(BaseBloomerpView, TemplateView):
    """Keep calendar navigation separate from the user's selected email folder."""

    template_name = "views/communication/inbox_calendar.html"

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Save the calendar selection and reload the ordinary dataview from that preference."""
        inbox = resolve_calendar_inbox(request.user, self.kwargs["inbox_id"])
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
        save_calendar_overlay_selection(request.user, inbox.pk, selection)
        context = self.get_context_data()
        return render(
            request,
            "cotton/features/dataviews/call.html",
            {
                "content_type_id": context["calendar_content_type_id"],
                "filters": context["calendar_filters"],
                "args": context["calendar_args"],
                "token": context["calendar_token"],
            },
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Embed the ordinary event dataview with the effective Inbox as a hidden filter."""
        inbox = resolve_calendar_inbox(self.request.user, self.kwargs["inbox_id"])
        context = super().get_context_data(**kwargs)
        context["inbox"] = inbox
        context["back_to_inbox_url"] = reverse("inbox")
        context["calendar_content_type_id"] = ContentType.objects.get_for_model(
            CalendarEvent
        ).pk
        selection = calendar_overlay_selection(self.request.user, inbox.pk)
        selected = list(
            calendar_overlay_inboxes(self.request.user, selection).values_list(
                "pk", flat=True
            )
        )
        selected = [str(pk) for pk in selected]
        context["calendar_filters"] = {
            "filter": json.dumps(
                [
                    {
                        "connector": "AND",
                        "conditions": [
                            {
                                "field_path": "inboxes",
                                "lookup_id": "values_in",
                                "value": selected or ["0"],
                            }
                        ],
                    }
                ]
            ),
            "cancelled": "false",
            "calendar_color_field": "inboxes",
            "calendar_color_values": ",".join(selected),
            "calendar_inbox": str(inbox.pk),
            "calendar_color_preferred": str(inbox.pk),
        }
        context["calendar_args"] = {"hide_filters": "inboxes,inboxes__in,cancelled"}

        context["calendar_token"] = self.issue_calendar_token(inbox.pk, selected)
        return context

    def issue_calendar_token(self, inbox_id: int, selected: list[str]) -> str:
        """Delegate event reads for validated overlay inboxes and writes for the current inbox only."""
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
            audience=str(self.request.user.pk),
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
