"""Keep sent invitations available until their organizer has cancelled them."""

from typing import Any

from django.http import HttpRequest, HttpResponse

from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.router import router
from bloomerp.views.generic.detail.delete import BloomerpDeleteView


@router.register(
    path="delete", name="Delete", url_name="delete", route_type="detail",
    models=[CalendarEvent], override=True,
)
class CalendarEventDeleteView(BloomerpDeleteView):
    """Require cancellation before generic deletion can discard a sent local invitation."""

    template_name = "views/communication/calendar/delete.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Point organizers to the update form while cancellation remains outstanding."""
        context = super().get_context_data(**kwargs)
        event = self.get_object()
        context["calendar_cancellation_required"] = bool(
            event.organizing_inbox_id and event.invitation_sent_at and not event.cancelled
        )
        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Reject hard deletion until the sent meeting has been explicitly cancelled."""
        self.object = self.get_object()
        context = self.get_context_data(object=self.object)
        if context["calendar_cancellation_required"]:
            return self.render_to_response(context, status=409)
        return super().post(request, *args, **kwargs)
