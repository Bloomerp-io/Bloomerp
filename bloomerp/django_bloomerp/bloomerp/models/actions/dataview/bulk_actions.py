"""Group the toolbar actions that operate on multiple records."""

from urllib.parse import urlencode

from django.utils.translation import gettext_noop

from bloomerp.models.definition import DataviewActionContext, DataviewActionGrouping
from bloomerp.permissions.definition import BloomerpPermission


def can_use_dataview_bulk_actions(context: DataviewActionContext) -> bool:
    """Offer the bulk actions dialog to viewers who can change or delete in bulk."""
    from bloomerp.permissions.manager import UserPolicyManager

    manager = UserPolicyManager(context.request.user)
    return (
        manager.has_global_permission(context.model, BloomerpPermission.BULK_CHANGE)
        or manager.has_global_permission(context.model, BloomerpPermission.BULK_DELETE)
    )


def dataview_bulk_actions_url(context: DataviewActionContext) -> str:
    """Open the bulk dialog and identify the Dataview to refresh on completion."""
    from django.urls import reverse

    url = reverse("components_bulk_actions", kwargs={"content_type_id": context.content_type.pk})
    if context.render_id:
        return f"{url}?{urlencode({'_dataview_instance': context.render_id})}"
    return url


def bulk_actions_group() -> DataviewActionGrouping:
    """Offer bulk operations for matching records and for the current selection."""
    from .bulk_all_matching import bulk_all_matching_action
    from .bulk_selected_records import bulk_selected_records_action

    return DataviewActionGrouping(
        id="bulk-actions",
        label=gettext_noop("Bulk Actions"),
        icon="fa fa-list-check",
        should_render_func=can_use_dataview_bulk_actions,
        shortcut="mod+3",
        actions=[bulk_all_matching_action(), bulk_selected_records_action()],
    )
