from bloomerp.lookups.builtins.utils import date_part_lookup


DAY = date_part_lookup(
    lookup_id="day",
    label="Day",
    django_expression="day",
    min_value=1,
    max_value=31,
)
