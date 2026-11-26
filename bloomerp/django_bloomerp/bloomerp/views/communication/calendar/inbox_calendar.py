"""Show the selected Inbox's shared calendar using the standard dataview grid."""

from typing import TYPE_CHECKING, Any

from django.contrib.contenttypes.models import ContentType
from django.utils.functional import cached_property
from django.views.generic import TemplateView

from bloomerp.communication.calendar.access import (
    calendar_event_access_rule,
    calendar_overlay_inboxes,
    calendar_overlay_selection,
    resolve_calendar_inbox,
)
from bloomerp.filters.definition import Filter, FilterCondition, Filters
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.router import router
from bloomerp.tokens import DataviewToken, RequestToken
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.dataview_mixin import DataviewMixin

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox import Inbox


@router.register(
    path="/inbox/<int:inbox_id>/calendar/",
    route_type="app",
    url_name="inbox_calendar",
    name="Inbox calendar",
)
class InboxCalendarView(BaseBloomerpView, DataviewMixin, TemplateView):
    """Keep calendar navigation separate from the user's selected email folder."""

    template_name = "views/communication/inbox_calendar.html"
    dataview_hide_filters = True

    @cached_property
    def inbox(self) -> "Inbox":
        """Resolve the calendar's owner Inbox through the viewer's access."""
        return resolve_calendar_inbox(self.request.user, self.kwargs["inbox_id"])

    @cached_property
    def selected_calendar_ids(self) -> list[str]:
        """Resolve the saved overlay selection to the current set of readable inboxes."""
        user = self.request.user
        selection = calendar_overlay_selection(user, self.inbox.pk)
        return [
            str(pk) for pk in calendar_overlay_inboxes(user, selection).values_list("pk", flat=True)
        ]

    def get_dataview_content_type_id(self) -> int:
        """Render calendar events in the shared dataview."""
        return ContentType.objects.get_for_model(CalendarEvent).pk

    def get_dataview_filters(self) -> Filters:
        """Limit the view to uncancelled events in the selected inboxes."""
        return [Filter(connector="AND", conditions=[
            FilterCondition(field_path="inboxes", lookup_id="values_in", value=self.selected_calendar_ids or ["0"]),
            FilterCondition(field_path="cancelled", lookup_id="equals", value=False),
        ])]

    def get_dataview_query_params(self) -> dict[str, str]:
        """Set the calendar renderer's color grouping and preferred inbox."""
        return {
            "calendar_color_field": "inboxes",
            "calendar_color_values": ",".join(self.selected_calendar_ids),
            "calendar_color_preferred": str(self.inbox.pk),
        }

    def get_dataview_args(self) -> dict[str, str]:
        """Give the frontend the current inbox for alignment and event creation."""
        return {"calendar_inbox": str(self.inbox.pk)}

    def get_dataview_request_token(self) -> RequestToken:
        """Set the calendar layout, available actions, and access for the selected inboxes."""
        layout = next(
            view for view in CalendarEvent.bloomerp_config.model_view_settings.default_dataviews
            if view.view_type == "calendar" and view.is_default
        )
        return RequestToken(
            policies={CalendarEvent: calendar_event_access_rule(self.inbox.pk, self.selected_calendar_ids)},
            dataviews={CalendarEvent: DataviewToken(
                dataview=layout,
                dataview_actions=["add_calendars", "add", "bookings", "back_to_inbox"],
            )},
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add inbox navigation around the shared calendar loader."""
        return {
            **super().get_context_data(**kwargs),
            "inbox": self.inbox,
        }
