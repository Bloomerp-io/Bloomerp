"""Show the dataview filters."""

from bloomerp.models.definition import DataviewHTMLAction


def filter_action() -> DataviewHTMLAction:
    """Show the dataview filters."""
    return DataviewHTMLAction(
        id="filter",
        template_name="components/objects/dataview_actions/filter.html",
        shortcut="mod+1",
    )
