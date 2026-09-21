"""Shared numeric field eligibility and Decimal destination contracts."""

from __future__ import annotations

from decimal import Decimal, DecimalException
from typing import Any

from django import forms
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models
from django.db.models import QuerySet

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.models.application_field import ApplicationField

MAX_EXPRESSION_NODES = 100
NUMERIC_MODEL_FIELDS = (
    models.IntegerField,
    models.FloatField,
    models.DecimalField,
)


def numeric_fields(model: type[models.Model]) -> QuerySet[ApplicationField]:
    """Return editable stored numeric fields suitable as arithmetic operands."""
    eligible_ids: list[int] = []
    fields = ApplicationField.get_for_model(model)
    for field in fields:
        try:
            model_field = model._meta.get_field(field.field)
        except FieldDoesNotExist:
            continue
        if (
            isinstance(model_field, NUMERIC_MODEL_FIELDS)
            and model_field.concrete
            and not model_field.primary_key
            and model_field.editable
            and field.get_form_field() is not None
        ):
            eligible_ids.append(field.pk)
    return fields.filter(pk__in=eligible_ids)


def calculation_target_fields(
    fields: QuerySet[ApplicationField],
) -> QuerySet[ApplicationField]:
    """Return property, editable numeric, and editable unbound text targets."""
    eligible_ids: list[int] = []
    for field in fields:
        if field.field_type == FIELD_TYPE_REGISTRY.PROPERTY.id:
            eligible_ids.append(field.pk)
            continue
        try:
            model_field = field._get_model_field()
            form_field = field.get_form_field()
        except (AttributeError, FieldDoesNotExist, LookupError, TypeError, ValueError):
            continue
        numeric = isinstance(model_field, NUMERIC_MODEL_FIELDS)
        text = (
            isinstance(model_field, (models.CharField, models.TextField))
            and isinstance(form_field, forms.CharField)
            and not bool(getattr(form_field, "choices", ()))
        )
        if (
            (numeric or text)
            and model_field.editable
            and form_field is not None
            and not form_field.disabled
        ):
            eligible_ids.append(field.pk)
    return fields.filter(pk__in=eligible_ids)


def decimal_value(value: Any, operand_name: str, *, noun: str = "Column") -> Decimal:
    """Convert one numeric operand to finite Decimal, treating blanks as zero."""
    if value in (None, ""):
        return Decimal(0)
    if isinstance(value, bool):
        raise forms.ValidationError(
            f"{noun} '{operand_name}' does not contain a numeric value."
        )
    try:
        converted = Decimal(str(value))
    except (DecimalException, TypeError, ValueError) as error:
        raise forms.ValidationError(
            f"{noun} '{operand_name}' does not contain a numeric value."
        ) from error
    if not converted.is_finite():
        raise forms.ValidationError(
            f"{noun} '{operand_name}' does not contain a finite numeric value."
        )
    return converted


def clean_numeric_destination(
    destination: ApplicationField,
    value: Decimal,
) -> int | float | Decimal:
    """Quantize and validate a result through a numeric destination contract."""
    model_field = destination._get_model_field()
    if isinstance(model_field, models.DecimalField):
        quantum = Decimal(1).scaleb(-model_field.decimal_places)
        try:
            value = value.quantize(quantum, context=model_field.context)
        except DecimalException as error:
            raise forms.ValidationError(
                f"Result does not fit destination column '{destination.field}'."
            ) from error
    form_field = destination.get_form_field()
    if form_field is None:
        raise forms.ValidationError(
            f"Destination column '{destination.field}' is not editable."
        )
    form_field.required = False
    try:
        cleaned = form_field.clean(value)
    except ValidationError as error:
        raise forms.ValidationError(
            f"Result is invalid for destination column '{destination.field}': "
            f"{'; '.join(error.messages)}"
        ) from error
    if isinstance(cleaned, (int, float, Decimal)) and not isinstance(cleaned, bool):
        return cleaned
    raise forms.ValidationError(
        f"Destination column '{destination.field}' is not numeric."
    )
