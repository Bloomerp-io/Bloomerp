import operator

from bloomerp.lookups.builtins.utils import count_lookup


COUNT_EQUALS = count_lookup(
    lookup_id="count_equals",
    label="Count equals",
    django_expression="exact",
    sql_operator="=",
    comparator=operator.eq,
    expressions=("count_equals", "count", "count__exact"),
)
