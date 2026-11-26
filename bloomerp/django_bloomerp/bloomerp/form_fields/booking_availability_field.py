"""Validate and serialize the booking availability editor's JSON submission."""

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from pydantic import ValidationError as SchemaValidationError

from bloomerp.communication.calendar.booking_availability import BookingLinkAvailability
from bloomerp.widgets.booking_availability_widget import BookingAvailabilityWidget


class BookingAvailabilityField(forms.JSONField):
    """Clean weekly windows, optional date bounds and date overrides."""

    widget = BookingAvailabilityWidget

    def __init__(self, **kwargs: Any) -> None:
        """Compare changes with the instance value instead of a second hidden input."""
        kwargs["show_hidden_initial"] = False
        super().__init__(**kwargs)

    def to_python(self, value: Any) -> Any:
        """Validate the submitted schedule and return its JSON-compatible representation."""
        decoded = super().to_python(value)
        if self.disabled:
            return decoded
        if decoded is None:
            return None if self.required else {}
        try:
            schedule = BookingLinkAvailability.model_validate(decoded)
        except SchemaValidationError as error:
            raise ValidationError([
                ValidationError(
                    "%(location)s%(message)s",
                    code="invalid_availability",
                    params={
                        "location": f"{'.'.join(map(str, issue['loc']))}: " if issue['loc'] else "",
                        "message": _(issue["msg"].removeprefix("Value error, ")),
                    },
                )
                for issue in error.errors(include_url=False)
            ]) from error
        return schedule.model_dump(mode="json", exclude_defaults=True)

    def _clean_bound_field(self, bound_field: forms.BoundField) -> Any:
        """Allow other booking fields to be edited without rewriting saved legacy JSON."""
        form = bound_field.form
        if not self.disabled and isinstance(form, forms.ModelForm) and not form.instance._state.adding:
            stored = getattr(form.instance, bound_field.name)
            if super().to_python(bound_field.data) == stored:
                return stored
        return super()._clean_bound_field(bound_field)

    def has_changed(self, initial: Any, data: Any) -> bool:
        """Keep read-only and untouched legacy schedules out of the form's changes."""
        if self.disabled:
            return False
        try:
            if super().to_python(data) == initial:
                return False
        except ValidationError:
            return True
        return super().has_changed(initial, data)
