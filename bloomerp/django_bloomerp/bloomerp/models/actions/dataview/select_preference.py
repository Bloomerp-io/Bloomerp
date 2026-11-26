"""Choose a saved dataview preference."""

from bloomerp.models.definition import DataviewHTMLAction


def select_preference_action() -> DataviewHTMLAction:
    """Choose a saved dataview preference."""
    return DataviewHTMLAction(
        id="select-preference",
        template_name="components/objects/dataview_actions/select_preference.html",
        shortcut="mod+6",
    )
