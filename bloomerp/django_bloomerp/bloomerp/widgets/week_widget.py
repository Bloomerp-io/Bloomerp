from django import forms


class WeekWidget(forms.TextInput):
    """HTML week input."""

    input_type = "week"

    def format_value(self, value):
        if value in forms.Field.empty_values:
            return value
        return str(value)
