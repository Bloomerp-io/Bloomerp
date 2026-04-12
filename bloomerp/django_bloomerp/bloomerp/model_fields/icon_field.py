from django.db import models
from bloomerp.form_fields.icon_field import IconFormField
from bloomerp.widgets.icon_picker_widget import IconPickerWidget, DEFAULT_ICON_CHOICES, get_icon_values


class IconField(models.CharField):
    """A CharField that stores a Font Awesome icon class and renders an icon picker widget."""

    def __init__(self, *args, icons=None, **kwargs):
        if "max_length" not in kwargs:
            kwargs["max_length"] = 100
        self.icons = icons if icons is not None else list(DEFAULT_ICON_CHOICES)
        super().__init__(*args, **kwargs)

    def formfield(self, **kwargs):
        icon_values = get_icon_values(self.icons)
        defaults = {
            "form_class": IconFormField,
            "widget": IconPickerWidget(icons=self.icons),
            "allowed_icons": icon_values,
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.icons != DEFAULT_ICON_CHOICES:
            kwargs["icons"] = self.icons
        return name, path, args, kwargs
