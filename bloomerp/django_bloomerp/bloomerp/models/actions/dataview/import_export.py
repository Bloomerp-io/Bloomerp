"""Group import and export actions on the dataview toolbar."""

from django.utils.translation import gettext_noop

from bloomerp.models.definition import DataviewActionDefinition, DataviewActionGrouping


def import_export_group(actions: list[DataviewActionDefinition]) -> DataviewActionGrouping:
    """Group the available transfer actions in their standard toolbar position."""
    return DataviewActionGrouping(
        id="import-export",
        label=gettext_noop("Import/Export"),
        icon="fa-solid fa-right-left",
        shortcut="mod+4",
        actions=actions,
    )
