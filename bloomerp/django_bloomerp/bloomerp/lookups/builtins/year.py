from bloomerp.lookups.builtins.utils import date_part_lookup


YEAR = date_part_lookup(
    lookup_id="year",
    label="Year",
    django_expression="year",
    min_value=1,
    max_value=9999,
)
