from bloomerp.lookups.builtins.utils import date_part_lookup


MONTH = date_part_lookup(
    lookup_id="month",
    label="Month",
    django_expression="month",
    min_value=1,
    max_value=12,
)
