from bloomerp.lookups.builtins.utils import date_part_lookup


WEEK = date_part_lookup(
    lookup_id="week",
    label="Week",
    django_expression="week",
    min_value=1,
    max_value=53,
)
