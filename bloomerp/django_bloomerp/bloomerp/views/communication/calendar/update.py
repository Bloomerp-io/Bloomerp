"""Edit an existing calendar event through the shared event composer."""

from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.generic.edit import FormView

from bloomerp.forms.communication.calendar_event import can_create_calendar_event
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.router import router
from bloomerp.views.communication.calendar.create import CalendarEventMixin
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView


@router.register(
    path="update/",
    url_name="update",
    name="Update",
    description="Update a calendar invite",
    route_type="detail",
    models=[CalendarEvent],
    override=True,
)
class CalendarEventUpdateView(CalendarEventMixin, BaseBloomerpDetailView, FormView):
    """Reuse creation's layout, validation, availability, and submission handling for edits."""

    def get_object(self) -> CalendarEvent:
        """Resolve one event consistently throughout permission checks and form binding."""
        if not hasattr(self, "object"):
            self.object = get_object_or_404(CalendarEvent, pk=self.kwargs["pk"])
        return self.object

    def has_permission(self) -> bool:
        """Require event editing permissions independently of invitation attendance."""
        return can_create_calendar_event(self.request.user, self.get_object())

    def get_form_kwargs(self) -> dict[str, Any]:
        """Bind the existing event to the same permission-aware composer form."""
        return {**super().get_form_kwargs(), "instance": self.get_object()}

    def get_initial(self) -> dict[str, Any]:
        """Load stored event values in its timezone, with inclusive all-day UI dates."""
        event = self.get_object()
        initial = {
            name: getattr(event, name)
            for name in ("title", "content", "location", "all_day", "event_timezone")
        }
        initial["inbox"] = event.organizing_inbox_id
        if event.all_day:
            initial.update(start_date=event.start_date, end_date=event.end_date - timedelta(days=1))
        else:
            zone = ZoneInfo(event.event_timezone)
            start, end = timezone.localtime(event.start, zone), timezone.localtime(event.end, zone)
            initial.update(start_date=start.date(), end_date=end.date(), start_time=start.time(), end_time=end.time())
        return initial

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Configure the shared editor URL and start its object detail sidebar collapsed."""
        context = super().get_context_data(**kwargs)
        context["form_url"] = self.get_object().get_absolute_url()
        context["detail_sidebar_force_close"] = True
        return context
