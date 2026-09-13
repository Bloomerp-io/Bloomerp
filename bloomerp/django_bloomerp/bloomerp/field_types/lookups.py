"""Shared lookup selections for built-in field types."""

from bloomerp.lookups import builtins as lookups

DATE_LOOKUPS = [
    lookups.EQUALS,
    lookups.GREATER_THAN,
    lookups.GREATER_THAN_OR_EQUAL,
    lookups.LESS_THAN,
    lookups.LESS_THAN_OR_EQUAL,
    lookups.TODAY,
    lookups.YESTERDAY,
    lookups.THIS_WEEK,
    lookups.LAST_WEEK,
    lookups.THIS_MONTH,
    lookups.LAST_MONTH,
    lookups.THIS_QUARTER,
    lookups.LAST_QUARTER,
    lookups.THIS_YEAR,
    lookups.LAST_YEAR,
    lookups.YEAR,
    lookups.MONTH,
    lookups.DAY,
    lookups.WEEK,
    lookups.IS_NULL,
    lookups.NOT_EQUALS,
    lookups.DAY_OF_WEEK,
    lookups.DAY_OF_WEEK_IN,
]

WEEK_LOOKUPS = [
    lookups.EQUALS,
    lookups.GREATER_THAN,
    lookups.GREATER_THAN_OR_EQUAL,
    lookups.LESS_THAN,
    lookups.LESS_THAN_OR_EQUAL,
    lookups.YEAR,
    lookups.WEEK,
    lookups.IS_NULL,
    lookups.NOT_EQUALS,
]

TIME_LOOKUPS = [
    lookups.EQUALS,
    lookups.GREATER_THAN,
    lookups.GREATER_THAN_OR_EQUAL,
    lookups.LESS_THAN,
    lookups.LESS_THAN_OR_EQUAL,
    lookups.IS_NULL,
    lookups.NOT_EQUALS,
]

ONE_TO_MANY_LOOKUPS = [
    lookups.ONE_TO_MANY_ADVANCED,
    lookups.COUNT_EQUALS,
    lookups.COUNT_GREATER_THAN,
    lookups.COUNT_GREATER_THAN_OR_EQUAL,
    lookups.COUNT_LESS_THAN,
    lookups.COUNT_LESS_THAN_OR_EQUAL,
]

BOOLEAN_LOOKUPS = [
    lookups.EQUALS,
    lookups.IS_NULL,
]

NUMERIC_LOOKUPS = [
    lookups.EQUALS,
    lookups.GREATER_THAN,
    lookups.GREATER_THAN_OR_EQUAL,
    lookups.LESS_THAN,
    lookups.LESS_THAN_OR_EQUAL,
    lookups.VALUES_IN,
    lookups.IS_NULL,
    lookups.NOT_EQUALS,
]

TEXT_LOOKUPS = [
    lookups.EQUALS,
    lookups.IEXACT,
    lookups.CONTAINS,
    lookups.STARTS_WITH,
    lookups.ENDS_WITH,
    lookups.VALUES_IN,
    lookups.IS_NULL,
    lookups.NOT_EQUALS,
]
