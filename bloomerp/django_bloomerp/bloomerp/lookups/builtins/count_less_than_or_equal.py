import operator

from bloomerp.lookups.builtins.utils import count_lookup


COUNT_LESS_THAN_OR_EQUAL = count_lookup(
    lookup_id="count_less_than_or_equal",
    label="Count less than or equal",
    django_expression="lte",
    sql_operator="<=",
    comparator=operator.le,
)
