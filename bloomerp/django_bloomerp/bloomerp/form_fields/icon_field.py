from django import forms

from bloomerp.widgets.icon_picker_widget import parse_icon_value

class IconFormField(forms.CharField):
    """Form field for selecting a Font Awesome icon value."""

    def __init__(self, *args, allowed_icons: list[str] | None = None, **kwargs):
        self.allowed_icons = allowed_icons
        super().__init__(*args, **kwargs)

    def validate(self, value):
        super().validate(value)
        if value in self.empty_values:
            return

        normalized_icon_value = parse_icon_value(value).get("icon", "")

        if self.allowed_icons and normalized_icon_value not in self.allowed_icons:
            raise forms.ValidationError("Select a valid icon.")
