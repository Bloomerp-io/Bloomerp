"""Show the selected Inbox's shared calendar using the standard dataview grid."""

from typing import Any

from bloomerp.communication.calendar.calendar_access import resolve_calendar_inbox
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.views.generic import TemplateView


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
        """Embed the ordinary event dataview with the effective Inbox as a hidden filter."""
        inbox = resolve_calendar_inbox(self.request.user, self.kwargs["inbox_id"])
        context = super().get_context_data(**kwargs)
        context["inbox"] = inbox
        context["back_to_inbox_url"] = reverse("inbox")
        context["calendar_content_type_id"] = ContentType.objects.get_for_model(
            CalendarEvent
        ).pk
        context["calendar_filters"] = {
            "inboxes": str(inbox.pk),
            "cancelled": "false",
            "calendar_color_field": "inboxes",
            "calendar_color_values": str(inbox.pk),
            "calendar_color_preferred": str(inbox.pk),
        }
        context["calendar_args"] = {"hide_filters": "inboxes,inboxes__in,cancelled"}
        return context
