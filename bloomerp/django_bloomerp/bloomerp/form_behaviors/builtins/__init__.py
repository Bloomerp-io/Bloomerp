"""Sample catalog; registration/discovery is intentionally not wired yet."""

from bloomerp.form_behaviors.builtins.calculate import CALCULATE
from bloomerp.form_behaviors.builtins.clear_value import CLEAR_VALUE
from bloomerp.form_behaviors.builtins.copy_field_value import COPY_FIELD_VALUE
from bloomerp.form_behaviors.builtins.fetch import FETCH
from bloomerp.form_behaviors.builtins.increment_o2m_value import INCREMENT_O2M_VALUE
from bloomerp.form_behaviors.builtins.set_field_interaction import (
    SET_FIELD_INTERACTION,
)
from bloomerp.form_behaviors.builtins.set_field_visibility import SET_FIELD_VISIBILITY
from bloomerp.form_behaviors.builtins.set_user_field_to_current_user import (
    SET_USER_FIELD_TO_CURRENT_USER,
)
from bloomerp.form_behaviors.builtins.show_message import SHOW_MESSAGE
from bloomerp.form_behaviors.builtins.transform_text import TRANSFORM_TEXT

from .populate_week_dates import POPULATE_WEEK_DATES
from .set_o2m_value import SET_O2M_VALUE
from .set_value import SET_VALUE

BUILTIN_ACTIONS = (
    SET_FIELD_VISIBILITY,
    SET_FIELD_INTERACTION,
    SET_VALUE,
    SET_O2M_VALUE,
    POPULATE_WEEK_DATES,
    COPY_FIELD_VALUE,
    SHOW_MESSAGE,
    INCREMENT_O2M_VALUE,
    CALCULATE,
    CLEAR_VALUE,
    TRANSFORM_TEXT,
    FETCH,
    SET_USER_FIELD_TO_CURRENT_USER,
)
