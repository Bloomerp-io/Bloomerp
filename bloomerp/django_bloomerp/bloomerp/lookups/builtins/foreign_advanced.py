"""Discover fields on a related model without compiling a predicate."""
from bloomerp.lookups.definition import LookupDefinition


def _nested_fields(model, field_path):
    from django.core.exceptions import ValidationError
    from bloomerp.filters.utils import (
        application_fields_to_filter_field_groups, resolve_model_path,
    )
    from bloomerp.models.application_field import ApplicationField

    if model is None:
        raise ValidationError("Relation traversal requires a model-backed field")
    _, field, json_keys = resolve_model_path(model, field_path)
    related_model = getattr(field, "related_model", None)
    if json_keys or related_model is None:
        raise ValidationError("Selected field is not a relation")
    return application_fields_to_filter_field_groups(ApplicationField.get_for_model(related_model))


FOREIGN_ADVANCED = LookupDefinition(
    id="foreign_advanced",
    label="Advanced",
    expressions=(),
    description="Delegates the remaining lookup path to the related model.",
    nested=True,
    nested_fields_factory=_nested_fields,
)
