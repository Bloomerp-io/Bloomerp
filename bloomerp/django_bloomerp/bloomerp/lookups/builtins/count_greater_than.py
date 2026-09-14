import operator

from bloomerp.lookups.builtins.utils import count_lookup


COUNT_GREATER_THAN = count_lookup(
    lookup_id="count_greater_than",
    label="Count greater than",
    django_expression="gt",
    sql_operator=">",
    comparator=operator.gt,
)
