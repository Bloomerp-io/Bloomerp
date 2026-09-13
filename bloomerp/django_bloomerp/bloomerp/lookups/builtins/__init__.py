"""Built-in lookup definitions."""

from .address_contains import ADDRESS_CONTAINS
from .contains import CONTAINS
from .count_equals import COUNT_EQUALS
from .count_greater_than import COUNT_GREATER_THAN
from .count_greater_than_or_equal import COUNT_GREATER_THAN_OR_EQUAL
from .count_less_than import COUNT_LESS_THAN
from .count_less_than_or_equal import COUNT_LESS_THAN_OR_EQUAL
from .day import DAY
from .day_of_week import DAY_OF_WEEK
from .day_of_week_in import DAY_OF_WEEK_IN
from .ends_with import ENDS_WITH
from .equals import EQUALS
from .equals_user import EQUALS_USER
from .foreign_advanced import FOREIGN_ADVANCED
from .greater_or_equal_than import GREATER_THAN_OR_EQUAL
from .greater_than import GREATER_THAN
from .iexact import IEXACT
from .is_null import IS_NULL
from .json_key import JSON_KEY
from .last_month import LAST_MONTH
from .last_quarter import LAST_QUARTER
from .last_week import LAST_WEEK
from .last_year import LAST_YEAR
from .less_or_equal_than import LESS_THAN_OR_EQUAL
from .less_than import LESS_THAN
from .month import MONTH
from .not_equals import NOT_EQUALS
from .not_in import NOT_IN
from .one_to_many_advanced import ONE_TO_MANY_ADVANCED
from .starts_with import STARTS_WITH
from .this_month import THIS_MONTH
from .this_quarter import THIS_QUARTER
from .this_week import THIS_WEEK
from .this_year import THIS_YEAR
from .today import TODAY
from .values_in import VALUES_IN
from .week import WEEK
from .year import YEAR
from .yesterday import YESTERDAY

BUILTIN_LOOKUPS = (
    ADDRESS_CONTAINS,
    CONTAINS,
    COUNT_EQUALS,
    COUNT_GREATER_THAN,
    COUNT_GREATER_THAN_OR_EQUAL,
    COUNT_LESS_THAN,
    COUNT_LESS_THAN_OR_EQUAL,
    DAY,
    DAY_OF_WEEK,
    DAY_OF_WEEK_IN,
    ENDS_WITH,
    EQUALS,
    EQUALS_USER,
    FOREIGN_ADVANCED,
    GREATER_THAN_OR_EQUAL,
    GREATER_THAN,
    IEXACT,
    IS_NULL,
    JSON_KEY,
    LAST_MONTH,
    LAST_QUARTER,
    LAST_WEEK,
    LAST_YEAR,
    LESS_THAN_OR_EQUAL,
    LESS_THAN,
    MONTH,
    NOT_EQUALS,
    NOT_IN,
    ONE_TO_MANY_ADVANCED,
    STARTS_WITH,
    THIS_MONTH,
    THIS_QUARTER,
    THIS_WEEK,
    THIS_YEAR,
    TODAY,
    VALUES_IN,
    WEEK,
    YEAR,
    YESTERDAY,
)
