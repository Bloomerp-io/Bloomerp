from bloomerp.lookups.definition import LookupDefinition
from bloomerp.lookups.builtins.foreign_advanced import _nested_fields


ONE_TO_MANY_ADVANCED = LookupDefinition(
    id="one_to_many_advanced",
    label="Advanced",
    expressions=(),
    description="Delegates the remaining lookup path to the related model.",
    nested=True,
    nested_fields_factory=_nested_fields,
)
