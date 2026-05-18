from django.core import exceptions
from django.db import models

from bloomerp.form_fields.address_field import AddressFormField, normalize_address_value
from bloomerp.widgets.address_widget import AddressWidget


class AddressField(models.JSONField):
    """Stores a postal address as structured JSON."""

    description = "Address"
    form_field_cls = AddressFormField
    widget_cls = AddressWidget

    def get_internal_type(self):
        return "AddressField"

    def db_type(self, connection):
        data = self.db_type_parameters(connection)
        column_type = connection.data_types["JSONField"]
        if callable(column_type):
            return column_type(data)
        return column_type % data

    def from_db_value(self, value, expression, connection):
        value = super().from_db_value(value, expression, connection)
        if value in self.empty_values:
            return value
        return normalize_address_value(value)

    def to_python(self, value):
        value = super().to_python(value)
        if value in self.empty_values:
            return value
        return normalize_address_value(value)

    def get_prep_value(self, value):
        normalized = self.to_python(value)
        if normalized in self.empty_values:
            return None
        return dict(normalized)

    def validate(self, value, model_instance):
        try:
            value = self.to_python(value)
        except exceptions.ValidationError as error:
            raise error
        super().validate(value, model_instance)

    def formfield(self, **kwargs):
        defaults = {
            "form_class": AddressFormField,
            "widget": AddressWidget,
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)
