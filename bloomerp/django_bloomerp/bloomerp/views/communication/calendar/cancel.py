"""Cancel a local calendar event without deleting its scheduling identity."""

import logging
from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext as _

from bloomerp.communication.calendar.outgoing import calendar_sender, send_calendar_request
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.communication.calendar.update import CalendarEventUpdateView


@transaction.atomic
def cancel_calendar_event(*, user: AbstractBloomerpUser, event_id: UUID) -> None:
    """Cancel once, delivering emailed cancellations before marking the local event cancelled."""
    event = CalendarEvent.objects.select_for_update().get(pk=event_id)
    manager = UserPolicyManager(user)
    if not manager.has_access_to_object(event, "view") or not manager.has_access_to_object(event, "change", fields=["cancelled"]):
        raise PermissionDenied("You cannot cancel this calendar event.")
    if event.organizing_inbox_id is None:
        raise PermissionDenied("Only locally organized events can be cancelled here.")
    if event.cancelled:
        return
    emailed_guests = event.participants.exclude(email="").exclude(email__iexact=event.organizer_email).exists()
    if event.invitation_sent_at is not None and emailed_guests:
        account = calendar_sender(user, event)
        send_calendar_request(user=user, event_id=event.pk, email_account_id=account.pk, cancel=True)
    else:
        event.cancelled = True
        event.save(update_fields=["cancelled"])


@router.register(
    path="cancel/", name="Cancel event", url_name="cancel", route_type="detail",
    models=[CalendarEvent], searchable=False,
)
class CalendarEventCancelView(CalendarEventUpdateView):
    """Handle cancellation separately while reusing the event editor for recoverable errors."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Cancel the saved event independently of any unfinished composer edits."""
        try:
            cancel_calendar_event(user=request.user, event_id=self.get_object().pk)
        except PermissionDenied:
            raise
        except Exception as error:
            if not isinstance(error, ValidationError):
                logging.getLogger(__name__).exception("Calendar cancellation failed: %s", self.get_object().pk)
            form = self.get_form()
            form.add_error(None, error if isinstance(error, ValidationError) else _("The event could not be cancelled. Please try again."))
            return self.form_invalid(form)
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response
