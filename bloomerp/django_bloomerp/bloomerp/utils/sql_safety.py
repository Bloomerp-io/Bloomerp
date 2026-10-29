"""Fail-closed syntax policy for user-authored analytics SQL.

Only reviewed reporting expressions are accepted. A SELECT can still execute
arbitrary SQL, access files, or change connection state through a function.
This module does no I/O and never caches user permissions or query results.
"""

from functools import lru_cache

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

# Match exact node classes: accepting all Func/Expression subclasses would also
# accept newly added or unreviewed parser features. Unknown forms fail closed.
_EXPRESSION_NAMES = frozenset(
    """
Select Union Intersect Except Subquery With CTE From Join Table TableAlias Identifier
Column Star Alias Distinct Where Group Having Order Ordered Limit Offset Window
ByteString RawString HexString BitString AtTimeZone WindowSpec Filter WithinGroup Paren Tuple Literal Boolean Null And Or Not EQ NEQ GT
GTE LT LTE Is In Between Exists Like ILike Escape Add Sub Mul Div IntDiv Mod Neg Pow
Concat DPipe BitwiseAnd BitwiseOr BitwiseXor BitwiseLeftShift BitwiseRightShift
BitwiseNot Case If Cast TryCast DataType DataTypeParam Interval Var Array Bracket
Slice JSONExtract JSONExtractScalar JSONPath JSONPathRoot JSONPathKey
JSONPathSubscript JSONPathWildcard JSONBContains Lateral
""".split()  # noqa: SIM905 - grouped for security review
)
_FUNCTION_NAMES = frozenset(
    """
Abs Avg Sum Min Max Count CountIf Coalesce Nullif Greatest Least Round Floor Ceil Sqrt
Cbrt Exp Ln Log Log2 Log10 Power Sign Lower Upper Length Substring Trim LTrim RTrim
Replace Concat ConcatWs Left Right StrPosition SplitPart Repeat Reverse LPad RPad Date
Datetime TsOrDsToTimestamp TsOrDsToDate DateAdd DateSub DateDiff DateTrunc TimestampTrunc TimeTrunc TimestampAdd TimestampSub
TimestampDiff Extract TimeToStr StrToTime CurrentDate CurrentTime CurrentTimestamp
RowNumber Rank DenseRank PercentRank CumeDist Ntile Lag Lead FirstValue LastValue
NthValue ArrayAgg ArraySize ArrayContains GroupConcat Stddev StddevPop StddevSamp
Variance VariancePop Corr CovarPop CovarSamp PercentileCont PercentileDisc Median
RegexpReplace LogicalAnd LogicalOr JSONBExtract JSONBExtractScalar JSONObject JSONArray
""".split()  # noqa: SIM905 - grouped for security review
)
_ALLOWED_TYPES = frozenset(
    getattr(exp, name)
    for name in _EXPRESSION_NAMES | _FUNCTION_NAMES
    if hasattr(exp, name)
)
# These built-ins have no dedicated node in one or both supported dialects.
_ANONYMOUS_FUNCTIONS = {
    "postgres": frozenset(
        {
            "json_build_object",
            "jsonb_build_object",
            "json_build_array",
            "jsonb_build_array",
            "jsonb_array_length",
            "jsonb_array_elements_text",
        }
    ),
    "sqlite": frozenset(
        {
            "strftime",
            "julianday",
            "unixepoch",
            "datetime",
            "time",
            "date",
            "total",
            "printf",
        }
    ),
}
# JSON expansion consumes only already-checked arguments; unlike dynamic SQL,
# it cannot independently open a relation or interpret SQL text.
_TABLE_FUNCTIONS = frozenset({"jsonb_array_elements_text"})
_CAST_TYPES = frozenset(
    """
BOOLEAN TINYINT SMALLINT INT BIGINT UTINYINT USMALLINT UINT UBIGINT FLOAT DOUBLE
DECIMAL CHAR NCHAR VARCHAR NVARCHAR TEXT BINARY VARBINARY DATE TIME TIMETZ TIMESTAMP
TIMESTAMPTZ INTERVAL UUID JSON JSONB ARRAY
""".split()  # noqa: SIM905 - grouped for security review
)
_MAX_QUERY_LENGTH = 100_000


def connection_dialect(vendor: str) -> str:
    """Map supported Django vendors to their SQLGlot dialect names."""
    try:
        return {"postgresql": "postgres", "sqlite": "sqlite"}[vendor]
    except KeyError as error:
        raise ValueError(f"Unsupported SQL permission dialect: {vendor}") from error


@lru_cache(maxsize=128)
def _validated_query(query: str, dialect: str) -> exp.Query:
    """Parse and validate bounded SQL, retaining a private immutable template."""
    try:
        statements = [
            statement for statement in parse(query, read=dialect) if statement
        ]
    except SqlglotError as error:
        raise ValueError("Invalid SQL query") from error
    if len(statements) != 1:
        raise ValueError("Exactly one SQL statement is required")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        raise ValueError("Only read-only SELECT/WITH queries are allowed")  # noqa: TRY004

    for node in tree.walk():
        if isinstance(node, exp.Anonymous):
            if not isinstance(
                node.this, str
            ) or node.name.lower() not in _ANONYMOUS_FUNCTIONS.get(dialect, ()):
                raise ValueError(f"Unsupported SQL function: {node.name}")
        elif type(node) not in _ALLOWED_TYPES:
            raise ValueError(f"Unsupported SQL expression: {type(node).__name__}")
        if isinstance(node, exp.Table) and not (
            isinstance(node.this, exp.Identifier)
            or isinstance(node.this, exp.Anonymous) and node.this.name.lower() in _TABLE_FUNCTIONS
        ):
            raise ValueError("Unsupported SQL table-valued function")
        if isinstance(node, exp.DataType) and node.this.name not in _CAST_TYPES:
            raise ValueError("Unsupported SQL cast type")
    return tree


def validate_read_query(query: str, dialect: str) -> None:
    """Reject unsupported SQL without executing it or copying the cached tree."""
    if len(query) > _MAX_QUERY_LENGTH:
        raise ValueError("SQL query is too long")
    _validated_query(query, dialect)


def parse_read_query(query: str, dialect: str) -> exp.Query:
    """Return an independently mutable validated tree for permission rewriting."""
    validate_read_query(query, dialect)
    return _validated_query(query, dialect).copy()


def is_safe_read_query(query: str, dialect: str) -> bool:
    """Return whether SQL uses only the supported read-only reporting grammar."""
    try:
        validate_read_query(query, dialect)
    except ValueError:
        return False
    return True
