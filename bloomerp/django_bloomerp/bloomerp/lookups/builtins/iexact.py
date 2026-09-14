from typing import Any

from bloomerp.lookups.builtins.utils import q_factory_for
from bloomerp.lookups.definition import CompiledSQL, LookupDefinition, SQLLookupContext


def iexact_sql_factory(
    context: SQLLookupContext,
    expression: str,
    value: Any,
) -> CompiledSQL:
    del expression
    return CompiledSQL(
        clause=f"LOWER({context.field_path}) = LOWER(%s)",
        parameters=(value,),
    )


def iexact(actual: Any, expected: Any) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return str(actual).casefold() == str(expected).casefold()


IEXACT = LookupDefinition(
    id="iexact",
    label="Equals (case-insensitive)",
    expressions=("iexact",),
    description="Matches text without regard to letter casing.",
    q_factory=q_factory_for("iexact"),
    sql_factory=iexact_sql_factory,
    python_evaluator=iexact,
)
