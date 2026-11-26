"""Clean the single persisted value used by the booking location widget."""

from typing import Any

from django import forms
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils.translation import gettext_lazy as _

from bloomerp.communication.builtins.conferencing.configuration import (
    get_conferencing_settings,
)
from bloomerp.widgets.booking_location_widget import (
    CREATE_BOOKING_CONFERENCE,
    BookingLocationWidget,
)


class BookingLocationField(forms.CharField):
    """Accept a location or a new meeting when conferencing is available."""

    widget = BookingLocationWidget

    def clean(self, value: Any) -> str:
        """Validate the text and check availability for an automatic meeting."""
        location = super().clean(value)
        if location == CREATE_BOOKING_CONFERENCE and not self.disabled:
            try:
                get_conferencing_settings()
            except ImproperlyConfigured as error:
                raise ValidationError(
                    _("Conferencing is unavailable for this instance."),
                    code="conferencing_unavailable",
                ) from error
        return location
