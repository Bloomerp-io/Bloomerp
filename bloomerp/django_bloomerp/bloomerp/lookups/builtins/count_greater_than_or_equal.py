import operator

from bloomerp.lookups.builtins.utils import count_lookup


COUNT_GREATER_THAN_OR_EQUAL = count_lookup(
    lookup_id="count_greater_than_or_equal",
    label="Count greater than or equal",
    django_expression="gte",
    sql_operator=">=",
    comparator=operator.ge,
)
