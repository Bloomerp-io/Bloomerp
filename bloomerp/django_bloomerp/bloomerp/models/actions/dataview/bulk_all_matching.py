"""Open the bulk dialog for all matching records."""

import json

from django.utils.translation import gettext_noop

from bloomerp.models.definition import DataviewModalAction

from .bulk_actions import dataview_bulk_actions_url


def bulk_all_matching_action() -> DataviewModalAction:
    """Open the bulk dialog for all matching records."""
    return DataviewModalAction(
        id="bulk-all-matching",
        label=gettext_noop("All matching records"),
        icon="fa fa-filter",
        endpoint=dataview_bulk_actions_url,
        modal_id="bulk-actions-modal",
        title=gettext_noop("Bulk actions"),
        button_attrs={"hx-vals": json.dumps({"selection": "filtered"}), "hx-push-url": "false"},
    )
