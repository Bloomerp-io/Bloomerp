"""Sample catalog; registration/discovery is intentionally not wired yet."""


from bloomerp.form_behaviors.builtins.increment_o2m_value import INCREMENT_O2M_VALUE
from bloomerp.form_behaviors.builtins.show_message import SHOW_MESSAGE

from .copy_value import COPY_VALUE
from .hide_field import HIDE_FIELD
from .set_value import SET_VALUE
from .set_o2m_value import SET_O2M_VALUE
from .populate_week_dates import POPULATE_WEEK_DATES
from .show_field import SHOW_FIELD

BUILTIN_ACTIONS = (
    HIDE_FIELD,
    SET_VALUE,
    SET_O2M_VALUE,
    POPULATE_WEEK_DATES,
    COPY_VALUE,
    SHOW_MESSAGE,
    SHOW_FIELD,
    INCREMENT_O2M_VALUE
)
