"""Open the shared calendar composer with a readable object's email recipient."""

import json
from functools import cached_property
from typing import Any
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.views.generic.edit import FormView

from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.router import router
from bloomerp.services.email_composer_services import (
    email_fields_for_object,
    resolve_email_object,
)
from bloomerp.utils.requests import render_message
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.communication.calendar.create import CalendarEventMixin


@router.register(
    path="components/communication/calendar/invite-for-object/",
    url_name="components_calendar_invite_for_object",
)
class InviteForObjectComponentView(CalendarEventMixin, BaseBloomerpView, FormView):
    """Reuse calendar validation, persistence, and invitation delivery in a detail modal."""

    @cached_property
    def contact(self) -> tuple[models.Model, dict[str, str]]:
        """Recheck object and email-field visibility on both opening and submitting the form."""
        try:
            obj = resolve_email_object(self.request.user, self.request.GET)
        except ValidationError as error:
            raise Http404 from error
        if obj is None:
            raise Http404
        for field in email_fields_for_object(self.request.user, obj):
            if field["name"] == self.request.GET.get("email_field"):
                return obj, field
        raise PermissionDenied

    def has_permission(self) -> bool:
        """Require normal event-creation grants and authorized contact provenance."""
        return super().has_permission() and bool(self.contact)

    def get_initial(self) -> dict[str, Any]:
        """Prefill the selected address through the regular calendar recipient editor."""
        return {**super().get_initial(), "attendees": self.contact[1]["value"]}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Retain source authorization when the shared form posts or displays validation errors."""
        context = super().get_context_data(**kwargs)
        obj, field = self.contact
        query = urlencode({
            "content_type_id": self.request.GET["content_type_id"],
            "object_id": str(obj.pk),
            "email_field": field["name"],
        })
        context["form_url"] = f"{reverse('components_calendar_invite_for_object')}?{query}"
        return context

    def get_success_response(self, event: CalendarEvent, notice: dict[str, str]) -> HttpResponse:
        """Close the contact dialog with the shared composer's save or delivery feedback."""
        response = render_message(self.request, notice["text"], notice["type"])
        response["HX-Trigger"] = json.dumps({
            "bloomerp:close-modal": {"modalId": "detail-calendar-modal"},
        })
        return response
