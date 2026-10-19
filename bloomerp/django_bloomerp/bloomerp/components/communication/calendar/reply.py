"""Reply to a calendar invitation through its own object modal action."""

import logging
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.edit import FormView

from bloomerp.communication.calendar.outgoing import respond_to_calendar_invitation
from bloomerp.forms.communication.calendar_event_response import CalendarEventResponseForm
from bloomerp.models import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.permissions.access_tokens import request_permission_token
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.layout_form_mixin import LayoutFormMixin


@router.register(
    path="components/communication/calendar/<uuid:event_id>/reply/",
    url_name="components_calendar_reply",
)
class ReplyCalendarInvitationComponentView(LayoutFormMixin, BaseBloomerpView, FormView):
    """Expose only the caller's attendance response, keeping event editing separate."""

    template_name = "components/communication/calendar/reply.html"
    form_class = CalendarEventResponseForm
    htmx_include_addendum = False
    ts_item_component = "detail-view-value"

    def get_object(self) -> CalendarEvent:
        """Resolve the invitation consistently across authorization, form setup, and submission."""
        if not hasattr(self, "object"):
            self.object = get_object_or_404(CalendarEvent, pk=self.kwargs["event_id"])
        return self.object

    def has_permission(self) -> bool:
        """Authorize the invited user or connected mailbox without granting event editing."""
        event = self.get_object()
        return event.get_participant(self.request.user) is not None and not event.is_host(self.request.user)

    def get_form(self, form_class: type[CalendarEventResponseForm] | None = None) -> CalendarEventResponseForm:
        """Reuse the bound attendance form when rendering its layout and validation errors."""
        if not hasattr(self, "_response_form"):
            self._response_form = super().get_form(form_class)
        return self._response_form

    def get_initial(self) -> dict[str, Any]:
        """Initialize attendance from the caller's invited identity and current revision."""
        event = self.get_object()
        return {"response_status": event.get_participant(self.request.user).response_status, "sequence": event.sequence}

    def get_layout(self) -> FieldLayout:
        """Render attendance through the shared form layout used by modal save controls."""
        return FieldLayout(rows=[LayoutRow(columns=1, items=[LayoutItem(id="response_status")])])

    def resolve_form_label(self, item: LayoutItem) -> str:
        """Resolve lazy translated labels before serializing the form layout."""
        return str(self.get_form()[str(item.id)].label)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Post replies to this component while retaining the current invitation capability."""
        context = super().get_context_data(**kwargs)
        event = self.get_object()
        context.update(
            calendar_event=event,
            participant=event.get_participant(self.request.user),
            permission_token=request_permission_token(self.request.user),
            form_url=reverse("components_calendar_reply", kwargs={"event_id": event.pk}),
        )
        return context

    def form_valid(self, form: CalendarEventResponseForm) -> HttpResponse:
        """Deliver external replies before recording success and preserve attendance on failure."""
        try:
            respond_to_calendar_invitation(
                user=self.request.user, event_id=self.get_object().pk,
                response_status=form.cleaned_data["response_status"],
                expected_sequence=form.cleaned_data["sequence"],
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        except PermissionDenied:
            raise
        except Exception:
            logging.getLogger(__name__).exception("Calendar response failed: %s", self.get_object().pk)
            form.add_error(None, _("Your response could not be sent. Please try again."))
            return self.form_invalid(form)
        messages.success(self.request, _("Attendance updated."))
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response
