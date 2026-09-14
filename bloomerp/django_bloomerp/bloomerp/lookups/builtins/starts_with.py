from typing import Any

from bloomerp.lookups.builtins.utils import q_factory_for, sql_factory_for
from bloomerp.lookups.definition import LookupDefinition


def starts_with(actual: Any, expected: Any) -> bool:
    if actual is None or expected is None:
        return False
    return str(actual).startswith(str(expected))


STARTS_WITH = LookupDefinition(
    id="starts_with",
    label="Starts with",
    expressions=("starts_with", "startswith"),
    description="Matches values beginning with the supplied text.",
    q_factory=q_factory_for("startswith"),
    sql_factory=sql_factory_for("LIKE", lambda value: f"{value}%"),
    python_evaluator=starts_with,
)
