from django.core import exceptions
from django.db import models

from bloomerp.form_fields.phone_number_field import (
    PhoneNumberFormField,
    normalize_phone_number,
)
from bloomerp.widgets.phone_number_widget import PhoneNumberWidget


class PhoneNumberField(models.CharField):
    """Stores phone numbers as normalized text while supporting country codes."""

    description = "Phone number"
    form_field_cls = PhoneNumberFormField
    widget_cls = PhoneNumberWidget

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 30)
        super().__init__(*args, **kwargs)

    def get_internal_type(self):
        return "PhoneNumberField"

    def to_python(self, value):
        value = super().to_python(value)
        if value in self.empty_values:
            return value
        return normalize_phone_number(value)

    def validate(self, value, model_instance):
        try:
            value = self.to_python(value)
        except exceptions.ValidationError as error:
            raise error
        super().validate(value, model_instance)

    def formfield(self, **kwargs):
        defaults = {
            "form_class": PhoneNumberFormField,
            "widget": PhoneNumberWidget,
            "max_length": self.max_length,
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)
