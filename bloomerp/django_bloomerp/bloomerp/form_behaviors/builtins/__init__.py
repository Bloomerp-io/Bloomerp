"""Sample catalog; registration/discovery is intentionally not wired yet."""

from bloomerp.form_behaviors.builtins.aggregate_o2m_column import AGGREGATE_O2M_COLUMN
from bloomerp.form_behaviors.builtins.calculate_field import CALCULATE_FIELD
from bloomerp.form_behaviors.builtins.calculate_o2m_row import CALCULATE_O2M_ROW
from bloomerp.form_behaviors.builtins.clear_value import CLEAR_VALUE
from bloomerp.form_behaviors.builtins.disable_field import DISABLE_FIELD
from bloomerp.form_behaviors.builtins.enable_field import ENABLE_FIELD
from bloomerp.form_behaviors.builtins.increment_o2m_value import INCREMENT_O2M_VALUE
from bloomerp.form_behaviors.builtins.show_message import SHOW_MESSAGE
from bloomerp.form_behaviors.builtins.transform_text import TRANSFORM_TEXT

from .copy_value import COPY_VALUE
from .hide_field import HIDE_FIELD
from .populate_week_dates import POPULATE_WEEK_DATES
from .set_o2m_value import SET_O2M_VALUE
from .set_value import SET_VALUE
from .show_field import SHOW_FIELD

BUILTIN_ACTIONS = (
    HIDE_FIELD,
    SET_VALUE,
    SET_O2M_VALUE,
    POPULATE_WEEK_DATES,
    COPY_VALUE,
    SHOW_MESSAGE,
    SHOW_FIELD,
    INCREMENT_O2M_VALUE,
    CALCULATE_O2M_ROW,
    CALCULATE_FIELD,
    CLEAR_VALUE,
    AGGREGATE_O2M_COLUMN,
    DISABLE_FIELD,
    ENABLE_FIELD,
    TRANSFORM_TEXT,
)
