from __future__ import annotations

from bloomerp.lookups.definition import BoundLookup, Lookup, LookupDefinition
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField
from bloomerp.utils.registry import BaseRegistry


class LookupRegistry(BaseRegistry[LookupDefinition]):
    """Registry and field-aware resolver for lookup definitions."""

    def get_lookup_by_expression(
        self,
        expression: str,
        field: ApplicationField,
    ) -> Lookup | None:
        nested_lookup = None
        for configured_lookup in field.get_lookups():
            lookup = BoundLookup.normalize(configured_lookup)
            if expression in lookup.expressions:
                return configured_lookup
            if lookup.nested:
                nested_lookup = configured_lookup
        return nested_lookup

    def get_by_id(self, id: str) -> LookupDefinition | None:
        return self.get(id)
    

LOOKUP_REGISTRY = LookupRegistry(LookupDefinition)



from bloomerp.lookups.builtins import BUILTIN_LOOKUPS

for lookup in BUILTIN_LOOKUPS:
    LOOKUP_REGISTRY.register(lookup.id, lookup)
