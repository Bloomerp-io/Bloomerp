"""Convert model metadata into the shared field-discovery contract."""
from bloomerp.filters.definition import FilterField, FilterFieldGroup
from bloomerp.lookups.definition import FilterFieldContext


def application_field_to_filter_field(application_field) -> FilterField:
    field_type = application_field.get_field_type()
    return FilterField(
        field=application_field.field,
        label=str(application_field.title),
        context=FilterFieldContext(
            field_type=field_type,
            application_field=application_field,
        ),
    )


def application_fields_to_filter_field_groups(application_fields) -> list[FilterFieldGroup]:
    fields = [
        application_field_to_filter_field(field)
        for field in application_fields if field.get_field_type().lookups
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
