from __future__ import annotations

from django.db.models import Model

from bloomerp.lookups.definition import LookupDefinition

def _nested_fields(model:Model, path:str) -> list[FilterField]:
    from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
    from bloomerp.filters.definition import FilterField
    return [
        FilterField(
            field="",
            label="Key",
            field_type=FIELD_TYPE_REGISTRY.EQUALS
        )
    ]


JSON_KEY = LookupDefinition(
    id="json_key",
    label="Advanced",
    expressions=(),
    description="Delegates the remaining lookup path to the related model.",
    nested=True,
    nested_fields_factory=_nested_fields
)
