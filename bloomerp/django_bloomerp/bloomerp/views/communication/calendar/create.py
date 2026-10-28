"""Compose calendar events from shared dataview modal defaults or the full create page."""

import json
import logging
from datetime import timedelta
from typing import Any

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic.edit import FormView

from bloomerp.communication.calendar.outgoing import CalendarSendUnconfirmed
from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.forms.communication.calendar_event import (
    CalendarEventCreateForm,
    can_create_calendar_event,
)
from bloomerp.models import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.permissions.access_tokens import request_permission_token
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.utils.models import get_create_view_url, get_list_view_url
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.layout_form_mixin import LayoutFormMixin


class CalendarEventMixin(LayoutFormMixin):
    
    model = CalendarEvent
    template_name = "views/communication/calendar/create.html"
    form_class = CalendarEventCreateForm
    htmx_include_addendum = False

    ts_item_component = "detail-view-value"

    def get_form(
        self, form_class: type[CalendarEventCreateForm] | None = None
    ) -> CalendarEventCreateForm:
        """Reuse one bound form for layout rendering, validation, and recipient identities."""
        if not hasattr(self, "_calendar_form"):
            self._calendar_form = super().get_form(form_class)
        return self._calendar_form

    def get_layout(self) -> FieldLayout:
        """Arrange permitted composer fields using the regular CRUD field layout."""
        form = self.get_form()
        sections = [
            (None, 2, [("inbox", 1), ("sender", 1)]),
            (None, 1, [("send_invitations", 1)]),
            (None, 1, [("title", 1), ("attendees", 1)]),
            (
                _("Timing"),
                6,
                [
                    ("all_day", 6),
                    ("start_date", 2),
                    ("start_time", 1),
                    ("end_date", 2),
                    ("end_time", 1),
                    ("event_timezone", 6),
                ],
            ),
            (
                None,
                1,
                [
                    ("location", 1),
                    ("create_conference", 1),
                    ("content", 1),
                ],
            ),
        ]
        return FieldLayout(
            rows=[
                LayoutRow(
                    columns=columns,
                    title=title,
                    items=[
                        LayoutItem(id=name, colspan=span)
                        for name, span in fields
                        if name in form.fields
                        and (name != "send_invitations" or "attendees" in form.fields)
                    ],
                )
                for title, columns, fields in sections
            ]
        )

    def resolve_form_label(self, item: LayoutItem) -> str:
        """Resolve translated form labels before serializing layout metadata."""
        return str(self.get_form()[str(item.id)].label)

    def render_extra_attrs(self, item: LayoutItem) -> dict[str, Any]:
        """Condition timing and email invitation controls on the composer's current selections."""
        attrs = {**super().render_extra_attrs(item), "data-max-cols": "6"}
        if item.id in {"start_time", "end_time", "event_timezone"}:
            attrs["x-show"] = "!allDay"
        if item.id == "send_invitations":
            attrs["x-show"] = "Boolean(senderSelected)"
            attrs["x-cloak"] = ""
        return attrs

    def has_permission(self) -> bool:
        """Require writable composition fields and one supported temporal representation."""
        return can_create_calendar_event(self.request.user)

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
            query.get("_arg_calendar_inbox")
            or query.get("inboxes")
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
            permission_token=request_permission_token(self.request.user),
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
        notice = {"text": _("Event updated.") if form.original is not None else _("Event created."), "type": "success"}
        cancellations_pending = bool(event.invitation_sent_at and event.participants.filter(invitation_cancelled=True).exists())
        if form.cleaned_data.get("send_invitations"):
            from bloomerp.communication.calendar.outgoing import send_calendar_request

            try:
                send_calendar_request(
                    user=self.request.user,
                    event_id=event.pk,
                    email_account_id=form.cleaned_data["sender"].pk,
                )
            except CalendarSendUnconfirmed as error:
                notice = {"text": error.messages[0], "type": "warning"}
            except Exception:
                logging.getLogger(__name__).exception(
                    "Calendar event saved but invitation delivery failed: %s", event.pk
                )
                notice = {
                    "text": _(
                        "Event saved, but invitations could not be sent. Edit the event to retry sending."
                    ),
                    "type": "warning",
                }
        elif cancellations_pending:
            from bloomerp.communication.calendar.outgoing import (
                send_removed_calendar_cancellations,
            )

            try:
                send_removed_calendar_cancellations(user=self.request.user, event_id=event.pk)
            except CalendarSendUnconfirmed as error:
                notice = {"text": error.messages[0], "type": "warning"}
            except Exception:
                logging.getLogger(__name__).exception("Removed attendee cancellation failed: %s", event.pk)
                notice = {
                    "text": _("Event saved, but guest cancellations could not be sent. Edit the event to retry sending."),
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
        if form.original is not None and self.request.htmx:
            response = HttpResponse(status=204)
            response["HX-Refresh"] = "true"
            return response
        return redirect(get_list_view_url(CalendarEvent))
    

@router.register(
    path="create/",
    route_type="model",
    url_name="add",
    name="Create event",
    override=True,
    models=[CalendarEvent],
)
class CreateCalendarEventView(CalendarEventMixin, BaseBloomerpView, FormView):
    """Create events with the same modal completion event as generic dataview creation."""
