"""Show the dataview display options."""

from bloomerp.models.definition import DataviewHTMLAction


def display_options_action() -> DataviewHTMLAction:
    """Show the dataview display options."""
    return DataviewHTMLAction(
        id="display-options",
        template_name="components/objects/dataview_actions/display_options.html",
        shortcut="mod+5",
    )
