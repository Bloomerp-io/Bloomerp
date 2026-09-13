from bloomerp.lookups.definition import LookupDefinition


ONE_TO_MANY_ADVANCED = LookupDefinition(
    id="one_to_many_advanced",
    label="Advanced",
    expressions=(),
    description="Delegates the remaining lookup path to the related model.",
    nested=True,
)
