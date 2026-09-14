import operator

from bloomerp.lookups.builtins.utils import compare, q_factory_for, sql_factory_for
from bloomerp.lookups.definition import LookupDefinition


GREATER_THAN = LookupDefinition(
    id="greater_than",
    label="Greater than",
    expressions=("greater_than", "gt"),
    q_factory=q_factory_for("gt"),
    sql_factory=sql_factory_for(">"),
    python_evaluator=lambda actual, expected: compare(actual, expected, operator.gt),
)
