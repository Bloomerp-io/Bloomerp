"""Convert model metadata into the shared field-discovery contract."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from django.db.models import Model

from bloomerp.filters.definition import Filter, FilterField, FilterFieldGroup
from bloomerp.lookups.definition import FilterFieldContext

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


def application_field_to_filter_field(application_field: ApplicationField) -> FilterField:
    """Expose the field's standard lookups and any model-specific additions."""
    field_type = application_field.get_field_type()
    extra_lookups = getattr(application_field.get_model(), "filter_lookups", {})
    if lookups := extra_lookups.get(application_field.field):
        field_type = replace(field_type, lookups=(*field_type.lookups, *lookups))
    return FilterField(
        field=application_field.field,
        label=str(application_field.title),
        context=FilterFieldContext(
            field_type=field_type,
            application_field=application_field,
        ),
    )


def application_fields_to_filter_field_groups(
    application_fields: Iterable[ApplicationField],
) -> list[FilterFieldGroup]:
    """Group fields that offer at least one filter lookup."""
    fields = [
        field for application_field in application_fields
        if (field := application_field_to_filter_field(application_field)).context.field_type.lookups
    ]
    return [FilterFieldGroup(name="Model fields", fields=fields)] if fields else []


def resolve_model_path(model, field_path):
    """Resolve Django structure only; callers enforce access separately.

    JSON keys are opaque data keys, never interpreted as model relations.
    Returns the owning model, concrete field, and any JSON-key suffix.
    """
    from django.core.exceptions import FieldDoesNotExist, ValidationError
    from django.db import models

    parts = field_path.split("__")
    if not parts or any(not part for part in parts):
        raise ValidationError("Invalid field path")
    owner = model
    for index, part in enumerate(parts):
        try:
            field = owner._meta.pk if part == "pk" else owner._meta.get_field(part)
        except FieldDoesNotExist as exc:
            raise ValidationError(f"Unknown field: {part}") from exc
        remaining = parts[index + 1:]
        if isinstance(field, models.JSONField):
            return owner, field, tuple(remaining)
        if not remaining:
            return owner, field, ()
        if not getattr(field, "related_model", None):
            raise ValidationError(f"Field {part!r} cannot be traversed")
        owner = field.related_model


def dict_to_filter(filter: dict[str, Any], *, model: type[Model]) -> Filter:
    """Convert Django field lookups into a shared AND filter for the model."""
    from bloomerp.filters.parser import parse_shorthand_filters

    filters = parse_shorthand_filters(filter, model=model)
    return filters[0] if filters else Filter(connector="AND")
