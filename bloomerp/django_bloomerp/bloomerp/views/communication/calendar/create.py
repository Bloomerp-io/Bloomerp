"""Compose calendar events from shared dataview modal defaults or the full create page."""

import json
import logging
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.forms.communication.calendar_event import (
    CalendarEventCreateForm,
    can_create_calendar_event,
)
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.utils.models import get_create_view_url, get_list_view_url
from bloomerp.views.base import BaseBloomerpView
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic.edit import FormView


@router.register(
    path="create/",
    route_type="model",
    url_name="add",
    name="Create event",
    override=True,
    models=[CalendarEvent],
)
class CreateCalendarEventView(BaseBloomerpView, FormView):
    """Create events with the same modal completion event as generic dataview creation."""

    model = CalendarEvent
    template_name = "views/communication/calendar/create.html"
    form_class = CalendarEventCreateForm
    htmx_include_addendum = False

    def has_permission(self) -> bool:
        """Require writable composition fields and one supported temporal representation."""
        return can_create_calendar_event(self.request.user)

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Serve the composer or bounded, permission-scoped availability for selected users."""
        if request.GET.get("action") == "availability":
            from bloomerp.services.calendar_availability import calendar_availability

            try:
                day = forms.DateField().clean(request.GET.get("day"))
                zone = ZoneInfo(
                    request.GET.get("timezone") or timezone.get_current_timezone_name()
                )
                identifiers = list(
                    dict.fromkeys([str(request.user.pk), *request.GET.getlist("users")])
                )
                if len(identifiers) > 100:
                    raise ValueError
                result = calendar_availability(request.user, identifiers, day, zone)
            except (ValidationError, ValueError, ZoneInfoNotFoundError):
                return JsonResponse(
                    {"error": _("Invalid availability request.")}, status=400
                )
            response = JsonResponse({"users": result})
            response["Cache-Control"] = "private, no-store"
            return response
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self) -> dict[str, Any]:
        """Provide the current user to calendar and field-permission validation."""
        return {
            **super().get_form_kwargs(),
            "user": self.request.user,
            "meeting_base_url": self.request.build_absolute_uri("/"),
        }

    def get_initial(self) -> dict[str, Any]:
        """Convert clicked cell boundaries to local controls and resolve shared Inbox references."""
        initial = super().get_initial()
        query = self.request.GET
        start = timezone.localtime().replace(
            minute=0, second=0, microsecond=0
        ) + timedelta(hours=1)
        end = start + timedelta(hours=1)
        try:
            start = (
                forms.DateTimeField(required=False).clean(query.get("start")) or start
            )
            end = forms.DateTimeField(required=False).clean(
                query.get("end")
            ) or start + timedelta(hours=1)
        except ValidationError:
            pass
        start, end = timezone.localtime(start), timezone.localtime(end)
        initial.update(
            start_date=start.date(),
            end_date=end.date(),
            start_time=start.time(),
            end_time=end.time(),
            event_timezone=timezone.get_current_timezone_name(),
        )
        if query.get("start_date"):
            try:
                first = forms.DateField().clean(query["start_date"])
                following = forms.DateField(required=False).clean(
                    query.get("end_date")
                ) or first + timedelta(days=1)
                initial.update(
                    all_day=True,
                    start_date=first,
                    end_date=max(first, following - timedelta(days=1)),
                )
            except ValidationError:
                pass
        available = PreferenceManager(self.request.user).get_available(Inbox)
        inbox_id = (
            query.get("inboxes")
            or (
                query.get("calendar_color_preferred")
                if query.get("inboxes__in")
                or (
                    query.get("calendar_color_field") == "inboxes"
                    and query.get("calendar_color_values")
                )
                else None
            )
            or query.get("inbox")
            or query.get("organizing_inbox")
        )
        if inbox_id:
            try:
                selected = available.filter(
                    Q(pk=inbox_id) | Q(source_object_id=inbox_id)
                ).first()
            except (ValueError, ValidationError):
                raise Http404("Inbox not found") from None
            if (
                selected is None
                or not accessible_inboxes(self.request.user)
                .filter(pk=selected.effective_preference.pk)
                .exists()
            ):
                raise Http404("Inbox not found")
        else:
            selected = available.filter(user=self.request.user, selected=True).first()
        if selected is not None:
            initial["inbox"] = selected.effective_preference.pk
        return initial

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Preserve modal correlation and the composer action through validation errors."""
        context = super().get_context_data(**kwargs)
        context.update(
            form_url=reverse(get_create_view_url(CalendarEvent)),
            data_view_create_id=self.request.POST.get("data_view_create_id")
            or self.request.GET.get("data_view_create_id", ""),
            calendar_timezone=timezone.get_current_timezone_name(),
        )
        form = context["form"]
        identities = {
            (person.email.lower() or f"user:{person.pk}"): str(person.pk)
            for person in getattr(form, "internal_attendees", [])
        }
        context["attendee_identities"] = json.dumps(identities)
        context["attendee_labels"] = json.dumps(
            {
                person.email.lower() or f"user:{person.pk}": str(person)
                for person in getattr(form, "internal_attendees", [])
            }
        )
        return context

    def form_valid(self, form: CalendarEventCreateForm) -> HttpResponse:
        """Save the event and close only its originating dataview modal on success."""
        try:
            event = form.save()
        except (ValidationError, PermissionDenied) as error:
            for message in getattr(
                error,
                "messages",
                [str(error) or _("You cannot send these invitations.")],
            ):
                form.add_error(None, message)
            return self.form_invalid(form)
        notice = {"text": _("Event created."), "type": "success"}
        if form.cleaned_data.get("send_invitations"):
            from bloomerp.communication.calendar.outgoing import send_calendar_request

            try:
                send_calendar_request(
                    user=self.request.user,
                    event_id=event.pk,
                    email_account_id=form.cleaned_data["sender"].pk,
                )
            except Exception:
                logging.getLogger(__name__).exception(
                    "Calendar event saved but invitation delivery failed: %s", event.pk
                )
                notice = {
                    "text": _(
                        "Event saved, but invitations could not be sent. Retry from the event's scheduling action."
                    ),
                    "type": "warning",
                }
        caller = self.request.POST.get("data_view_create_id") or self.request.GET.get(
            "data_view_create_id"
        )
        if caller:
            response = HttpResponse(status=204)
            response["HX-Trigger"] = json.dumps(
                {
                    "bloomerp:data-view-object-created": {
                        "data_view_create_id": caller,
                        "object_id": str(event.pk),
                        "messages": [notice],
                    }
                }
            )
            return response
        from django.contrib import messages

        messages.add_message(
            self.request,
            messages.WARNING if notice["type"] == "warning" else messages.SUCCESS,
            notice["text"],
        )
        return redirect(get_list_view_url(CalendarEvent))
