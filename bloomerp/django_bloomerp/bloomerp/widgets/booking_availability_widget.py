"""Render the booking availability editor and its serialized form control."""

import json
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from bloomerp.communication.calendar.booking_availability import Weekday


class BookingAvailabilityWidget(forms.Widget):
    """Expose weekly hours and date overrides through a single Django form value."""

    template_name = "widgets/booking_availability.html"

    def format_value(self, value: Any) -> str:
        """Keep submitted JSON or serialize the stored schedule for the editor."""
        if isinstance(value, str):
            return value
        return json.dumps({} if value is None else value)

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Provide translated weekday labels alongside stable schedule keys."""
        context = super().get_context(name, value, attrs)
        context["weekdays"] = list(zip(Weekday, (
            _("Monday"), _("Tuesday"), _("Wednesday"), _("Thursday"),
            _("Friday"), _("Saturday"), _("Sunday"),
        ), strict=True))
        return context
