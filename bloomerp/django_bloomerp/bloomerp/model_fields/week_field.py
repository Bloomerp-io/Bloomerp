from django.core import exceptions
from django.db import models

from bloomerp.form_fields.week_field import WeekFormField, normalize_week_value
from bloomerp.widgets.week_widget import WeekWidget


class WeekYearTransform(models.Transform):
    lookup_name = "year"
    output_field = models.IntegerField()

    def as_sql(self, compiler, connection):
        lhs, params = compiler.compile(self.lhs)
        return f"CAST(SUBSTR({lhs}, 1, 4) AS integer)", params


class WeekNumberTransform(models.Transform):
    lookup_name = "week"
    output_field = models.IntegerField()

    def as_sql(self, compiler, connection):
        lhs, params = compiler.compile(self.lhs)
        return f"CAST(SUBSTR({lhs}, 7, 2) AS integer)", params


class WeekField(models.CharField):
    """Stores an ISO week as YYYY-Www while exposing year/week properties."""

    description = "ISO week"
    form_field_cls = WeekFormField
    widget_cls = WeekWidget

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 8)
        super().__init__(*args, **kwargs)

    def get_internal_type(self):
        return "WeekField"

    def db_type(self, connection):
        data = self.db_type_parameters(connection)
        column_type = connection.data_types["CharField"]
        if callable(column_type):
            return column_type(data)
        return column_type % data

    def from_db_value(self, value, expression, connection):
        if value in self.empty_values:
            return value
        return normalize_week_value(value)

    def to_python(self, value):
        value = super().to_python(value)
        if value in self.empty_values:
            return value
        return normalize_week_value(value)

    def get_prep_value(self, value):
        value = self.to_python(value)
        if value in self.empty_values:
            return value
        return str(value)

    def validate(self, value, model_instance):
        try:
            value = self.to_python(value)
        except exceptions.ValidationError as error:
            raise error
        super().validate(value, model_instance)

    def formfield(self, **kwargs):
        defaults = {
            "form_class": WeekFormField,
            "widget": WeekWidget,
            "max_length": self.max_length,
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)


WeekField.register_lookup(WeekYearTransform)
WeekField.register_lookup(WeekNumberTransform)
