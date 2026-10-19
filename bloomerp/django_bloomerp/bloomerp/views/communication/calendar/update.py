"""Edit an existing calendar event through the shared event composer."""

import logging
from datetime import timedelta
from functools import cached_property
from typing import Any
from zoneinfo import ZoneInfo

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic.edit import FormView

from bloomerp.communication.calendar.outgoing import respond_to_calendar_invitation
from bloomerp.forms.communication.calendar_event import (
    CalendarEventCreateForm,
    can_create_calendar_event,
)
from bloomerp.forms.communication.calendar_event_response import (
    CalendarEventResponseForm,
)
from bloomerp.models import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.permissions.access_tokens import request_permission_token
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
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

    @cached_property
    def participant_response(self) -> bool:
        """Give invited non-hosts an attendance form instead of the organizer editor."""
        event = self.get_object()
        return event.get_participant(self.request.user) is not None and not event.is_host(self.request.user)

    def get_form(
        self, form_class: type[forms.Form] | None = None
    ) -> CalendarEventCreateForm | CalendarEventResponseForm:
        """Keep the existing composer for hosts and bind only attendance fields for participants."""
        if self.participant_response:
            if not hasattr(self, "_calendar_form"):
                self._calendar_form = CalendarEventResponseForm(**self.get_form_kwargs())
            return self._calendar_form
        return super().get_form(form_class)

    def has_permission(self) -> bool:
        """Allow own attendance responses or the existing policy-checked event editor."""
        return self.participant_response or can_create_calendar_event(self.request.user, self.get_object())

    def get_layout(self) -> FieldLayout:
        """Give the attendance form the layout expected by the shared CRUD component."""
        if self.participant_response:
            return FieldLayout(
                rows=[LayoutRow(columns=1, items=[LayoutItem(id="response_status")])]
            )
        return super().get_layout()

    def get_form_kwargs(self) -> dict[str, Any]:
        """Bind the existing event to the same permission-aware composer form."""
        if self.participant_response:
            return FormView.get_form_kwargs(self)
        return {**super().get_form_kwargs(), "instance": self.get_object()}

    def get_initial(self) -> dict[str, Any]:
        """Load stored event values in its timezone, with inclusive all-day UI dates."""
        event = self.get_object()
        if self.participant_response:
            return {"response_status": event.get_participant(self.request.user).response_status, "sequence": event.sequence}
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
        """Post updates to the event's overridden absolute URL using the shared template."""
        if self.participant_response:
            self.template_name = "views/communication/calendar/respond.html"
            context = BaseBloomerpView.get_context_data(self, **kwargs)
            context.update(
                layout=self.get_transformed_layout(),
                calendar_event=self.get_object(),
                participant=self.get_object().get_participant(self.request.user),
                permission_token=request_permission_token(self.request.user),
            )
        else:
            context = super().get_context_data(**kwargs)
        context["form_url"] = self.get_object().get_absolute_url()
        return context

    def form_valid(self, form: CalendarEventCreateForm | CalendarEventResponseForm) -> HttpResponse:
        """Save only the caller's attendance, delivering external replies before recording success."""
        if not self.participant_response:
            return super().form_valid(form)
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
        if self.request.htmx:
            response = HttpResponse(status=204)
            response["HX-Refresh"] = "true"
            return response
        return redirect(self.get_object().get_absolute_url())
