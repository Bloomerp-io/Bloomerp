import operator

from bloomerp.lookups.builtins.utils import compare, q_factory_for, sql_factory_for
from bloomerp.lookups.definition import LookupDefinition


LESS_THAN_OR_EQUAL = LookupDefinition(
    id="less_than_or_equal",
    label="Less than or equal",
    expressions=("less_than_or_equal", "lte"),
    q_factory=q_factory_for("lte"),
    sql_factory=sql_factory_for("<="),
    python_evaluator=lambda actual, expected: compare(actual, expected, operator.le),
)
