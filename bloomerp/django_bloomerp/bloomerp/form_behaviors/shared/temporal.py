"""Editable temporal field contracts and whole-unit date arithmetic."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from django import forms
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from bloomerp.models.application_field import ApplicationField

TemporalKind = Literal["date", "datetime"]


def temporal_kind(field: ApplicationField) -> TemporalKind | None:
    """Identify editable stored dates without mistaking datetime subclasses for dates."""
    try:
        model_field = field._get_model_field()
        form_field = field.get_form_field()
    except (AttributeError, FieldDoesNotExist, LookupError, TypeError, ValueError):
        return None
    if (
        not isinstance(model_field, models.DateField)
        or not model_field.concrete
        or model_field.primary_key
        or not model_field.editable
        or form_field is None
        or form_field.disabled
    ):
        return None
    if isinstance(model_field, models.DateTimeField):
        return "datetime" if isinstance(form_field, forms.DateTimeField) else None
    return "date" if isinstance(form_field, forms.DateField) else None


def temporal_fields(fields: QuerySet[ApplicationField]) -> QuerySet[ApplicationField]:
    """Keep only concrete editable scalar date and datetime fields."""
    return fields.filter(pk__in=[field.pk for field in fields if temporal_kind(field)])


def clean_temporal_value(field: ApplicationField, value: Any) -> date | datetime | None:
    """Clean a temporal operand through its form contract, preserving empty dates."""
    if temporal_kind(field) is None:
        raise forms.ValidationError(
            _("Field '%(field)s' is not an editable date or datetime.") % {'field': field.field}
        )
    form_field = field.get_form_field()
    form_field.required = False
    return form_field.clean(value)


def shift_temporal(value: date | datetime, offset: Decimal) -> date | datetime:
    """Add whole days to dates or whole minutes to datetimes within their range."""
    if not offset.is_finite() or offset != offset.to_integral_value():
        raise forms.ValidationError(_("Date and datetime offsets must be a whole number."))
    maximum = Decimal(999999999 * 24 * 60 if isinstance(value, datetime) else 999999999)
    if offset.copy_abs() > maximum:
        raise forms.ValidationError(
            _("The date or datetime offset is outside the supported range.")
        )
    try:
        delta = (
            timedelta(minutes=int(offset))
            if isinstance(value, datetime)
            else timedelta(days=int(offset))
        )
        if isinstance(value, datetime) and value.utcoffset() is not None:
            return (value.astimezone(UTC) + delta).astimezone(value.tzinfo)
        return value + delta
    except (OverflowError, ValueError) as error:
        raise forms.ValidationError(
            _("The date or datetime offset is outside the supported range.")
        ) from error
