"""Schema-free JSON key discovery; an empty field denotes a user-entered key."""
from bloomerp.lookups.definition import LookupDefinition


def _nested_fields(model, path):
    from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
    from bloomerp.filters.definition import FilterField, FilterFieldGroup
    from bloomerp.lookups.definition import FilterFieldContext

    field_type = FIELD_TYPE_REGISTRY.JSON_FIELD
    return [FilterFieldGroup(name="JSON keys", fields=[FilterField(
        field="", label="Key",
        context=FilterFieldContext(field_type=field_type),
    )])]


JSON_KEY = LookupDefinition(
    id="json_key",
    label="Key",
    expressions=(),
    description="Select a JSON object key; keys retain JSON value semantics.",
    nested=True,
    nested_fields_factory=_nested_fields,
)
