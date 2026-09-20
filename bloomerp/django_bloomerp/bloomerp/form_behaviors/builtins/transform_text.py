"""Transform a text listener into a declared text target without persistence."""

from __future__ import annotations

import re
from typing import Literal, cast

from django import forms
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.text import slugify

from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldValueUpdate,
)
from bloomerp.models.application_field import ApplicationField

Transformation = Literal[
    "uppercase",
    "lowercase",
    "title_case",
    "sentence_case",
    "trim",
    "collapse_whitespace",
    "upper_snake_case",
    "lower_snake_case",
    "slug",
]

TRANSFORMATION_CHOICES: tuple[tuple[Transformation, str], ...] = (
    ("uppercase", "Uppercase"),
    ("lowercase", "Lowercase"),
    ("title_case", "Title case"),
    ("sentence_case", "Sentence case"),
    ("trim", "Trim"),
    ("collapse_whitespace", "Collapse whitespace"),
    ("upper_snake_case", "Upper snake case"),
    ("lower_snake_case", "Lower snake case"),
    ("slug", "Slug"),
)


class TransformTextForm(forms.Form):
    """Select one deterministic text normalization operation."""

    transformation = forms.ChoiceField(choices=TRANSFORMATION_CHOICES)


def _is_editable_text_field(field: ApplicationField) -> bool:
    """Recognize text-shaped model and form contracts for one concrete field."""
    try:
        model_field = field._get_model_field()
        form_field = field.get_form_field()
    except (AttributeError, FieldDoesNotExist, LookupError, TypeError, ValueError):
        return False
    return (
        isinstance(model_field, (models.CharField, models.TextField))
        and isinstance(form_field, forms.CharField)
        and not form_field.disabled
        and not bool(getattr(form_field, "choices", ()))
    )


def text_fields(
    fields: QuerySet[ApplicationField],
) -> QuerySet[ApplicationField]:
    """Restrict an authorized field catalog to editable character/text contracts."""
    eligible_ids = [field.pk for field in fields if _is_editable_text_field(field)]
    return fields.filter(pk__in=eligible_ids)


def text_targets(
    fields: QuerySet[ApplicationField],
    listener: ApplicationField | None,
) -> QuerySet[ApplicationField]:
    """Offer editable character/text targets independently of the concrete model."""
    return text_fields(fields)


def _snake_case(value: str, *, uppercase: bool) -> str:
    """Apply ASCII slug normalization with underscore separators and chosen case."""
    normalized = re.sub(r"_+", "_", slugify(value).replace("-", "_")).strip("_")
    return normalized.upper() if uppercase else normalized.lower()


def _transform(value: str, transformation: Transformation) -> str:
    """Apply one documented transformation to a non-empty string."""
    if transformation == "uppercase":
        return value.upper()
    if transformation == "lowercase":
        return value.lower()
    if transformation == "title_case":
        return value.title()
    if transformation == "sentence_case":
        return value[:1].upper() + value[1:].lower()
    if transformation == "trim":
        return value.strip()
    if transformation == "collapse_whitespace":
        return re.sub(r"\s+", " ", value).strip()
    if transformation == "upper_snake_case":
        return _snake_case(value, uppercase=True)
    if transformation == "lower_snake_case":
        return _snake_case(value, uppercase=False)
    return slugify(value)


def transform_text(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Transform the listener string and suggest it for the declared target field."""
    value = context.listener_value
    if value in (None, ""):
        transformed = ""
    elif not isinstance(value, str):
        raise forms.ValidationError("Transform text requires a string listener value.")
    else:
        transformed = _transform(value, cast(Transformation, config["transformation"]))
    return BehaviorResult(
        values=(FieldValueUpdate(field=context.target_field, value=transformed),)
    )


def transform_text_config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Return the deterministic text-transformation configuration form."""
    return TransformTextForm


TRANSFORM_TEXT = BehaviorActionDefinition(
    id="transform_text",
    label="Transform text",
    description="Apply a deterministic text normalization to the listener value.",
    requires_target_field=True,
    config_form_factory=transform_text_config_form_factory,
    get_listener_fields=text_fields,
    get_target_fields=text_targets,
    execute=transform_text,
)
