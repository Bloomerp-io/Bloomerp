"""Render a booking location and the option to generate a meeting."""

from typing import Any

from django import forms

CREATE_BOOKING_CONFERENCE = ":bloomerp:conference"


class BookingLocationWidget(forms.TextInput):
    """Submit a free-form location or the reserved automatic meeting value."""

    template_name = "widgets/booking_location.html"

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Split the stored value into its text and checkbox presentation."""
        create_meeting = value == CREATE_BOOKING_CONFERENCE
        context = super().get_context(name, "" if create_meeting else value, attrs)
        context["widget"]["create_meeting"] = create_meeting
        context["widget"]["meeting_value"] = CREATE_BOOKING_CONFERENCE
        return context

    def value_from_datadict(self, data: Any, files: Any, name: str) -> str | None:
        """Use the reserved value when the meeting checkbox is checked."""
        if forms.CheckboxInput().value_from_datadict(data, files, f"{name}__meeting"):
            return CREATE_BOOKING_CONFERENCE
        return super().value_from_datadict(data, files, name)

    def value_omitted_from_data(self, data: Any, files: Any, name: str) -> bool:
        """Recognize both controls when applying a partial layout update."""
        return name not in data and f"{name}__meeting" not in data
