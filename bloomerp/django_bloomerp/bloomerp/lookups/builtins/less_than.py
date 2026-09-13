import operator

from bloomerp.lookups.builtins.utils import compare, q_factory_for, sql_factory_for
from bloomerp.lookups.definition import LookupDefinition


LESS_THAN = LookupDefinition(
    id="less_than",
    label="Less than",
    expressions=("less_than", "lt"),
    q_factory=q_factory_for("lt"),
    sql_factory=sql_factory_for("<"),
    python_evaluator=lambda actual, expected: compare(actual, expected, operator.lt),
)
