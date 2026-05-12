from django import forms


class PhoneNumberWidget(forms.TextInput):
    """HTML telephone input with sensible defaults for international numbers."""

    input_type = "tel"

    def __init__(self, attrs=None):
        default_attrs = {
            "autocomplete": "tel",
            "inputmode": "tel",
            "placeholder": "+32 470 12 34 56",
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)
