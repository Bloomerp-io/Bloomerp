"""Show the selected Inbox's shared calendar using the standard dataview grid."""

import json
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest
from django.urls import reverse
from django.views.generic import TemplateView

from bloomerp.communication.calendar.access import (
    calendar_overlay_inboxes,
    calendar_overlay_selection,
    issue_calendar_token,
    resolve_calendar_inbox,
)
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView


def inbox_calendar_context(request: HttpRequest, inbox_id: int) -> dict[str, Any]:
    """Build the shared dataview loader context for the Inbox page and alignment component."""
    inbox = resolve_calendar_inbox(request.user, inbox_id)
    context: dict[str, Any] = {}
    context["inbox"] = inbox
    context["back_to_inbox_url"] = reverse("inbox")
    context["calendar_content_type_id"] = ContentType.objects.get_for_model(
        CalendarEvent
    ).pk
    selection = calendar_overlay_selection(request.user, inbox.pk)
    selected = list(
        calendar_overlay_inboxes(request.user, selection).values_list("pk", flat=True)
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
        "_arg_calendar_inbox": str(inbox.pk),
        "calendar_color_preferred": str(inbox.pk),
    }
    context["calendar_args"] = {"hide_filters": "inboxes,inboxes__in,cancelled"}

    context["calendar_token"] = issue_calendar_token(request.user, inbox.pk, selected)
    return context


@router.register(
    path="/inbox/<int:inbox_id>/calendar/",
    route_type="app",
    url_name="inbox_calendar",
    name="Inbox calendar",
)
class InboxCalendarView(BaseBloomerpView, TemplateView):
    """Keep calendar navigation separate from the user's selected email folder."""

    template_name = "views/communication/inbox_calendar.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Embed the shared calendar using the saved and permission-checked Inbox selection."""
        return {
            **super().get_context_data(**kwargs),
            **inbox_calendar_context(self.request, self.kwargs["inbox_id"]),
        }
