from django import forms

class IconFormField(forms.CharField):
    """Form field for selecting a Font Awesome icon value."""

    def __init__(self, *args, allowed_icons: list[str] | None = None, **kwargs):
        self.allowed_icons = allowed_icons
        super().__init__(*args, **kwargs)

    def validate(self, value):
        super().validate(value)
        if value in self.empty_values:
            return

        if self.allowed_icons and value not in self.allowed_icons:
            raise forms.ValidationError("Select a valid icon.")
