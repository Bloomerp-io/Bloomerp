"""Open the bulk dialog for selected records."""

import json

from django.utils.translation import gettext_noop

from bloomerp.models.definition import DataviewModalAction

from .bulk_actions import dataview_bulk_actions_url


def bulk_selected_records_action() -> DataviewModalAction:
    """Open the bulk dialog for selected records."""
    return DataviewModalAction(
        id="bulk-selected-records",
        label=gettext_noop("Selected records"),
        icon="fa fa-list-check",
        endpoint=dataview_bulk_actions_url,
        modal_id="bulk-actions-modal",
        title=gettext_noop("Bulk actions"),
        requires_selection=True,
        button_attrs={"hx-vals": json.dumps({"selection": "selected"}), "hx-push-url": "false"},
    )
