import operator

from bloomerp.lookups.builtins.utils import count_lookup


COUNT_LESS_THAN = count_lookup(
    lookup_id="count_less_than",
    label="Count less than",
    django_expression="lt",
    sql_operator="<",
    comparator=operator.lt,
)
