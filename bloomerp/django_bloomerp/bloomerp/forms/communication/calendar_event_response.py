"""A participant may change attendance without editing the shared meeting."""

from django import forms
from django.utils.translation import gettext_lazy as _

from bloomerp.models.communication.calendar import CalendarEventParticipant


class CalendarEventResponseForm(forms.Form):
    """Validate a response against the meeting revision displayed to the participant."""

    response_status = forms.ChoiceField(
        label=_("Attendance"),
        choices=[
            (status.value, status.label)
            for status in CalendarEventParticipant.ResponseStatus
            if status != CalendarEventParticipant.ResponseStatus.AWAITING_RESPONSE
        ],
        widget=forms.Select(attrs={"class": "select w-full"}),
    )
    sequence = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
