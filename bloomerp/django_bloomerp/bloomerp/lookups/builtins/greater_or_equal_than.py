import operator

from bloomerp.lookups.builtins.utils import compare, q_factory_for, sql_factory_for
from bloomerp.lookups.definition import LookupDefinition


GREATER_THAN_OR_EQUAL = LookupDefinition(
    id="greater_than_or_equal",
    label="Greater than or equal",
    expressions=("greater_than_or_equal", "gte"),
    q_factory=q_factory_for("gte"),
    sql_factory=sql_factory_for(">="),
    python_evaluator=lambda actual, expected: compare(actual, expected, operator.ge),
)
