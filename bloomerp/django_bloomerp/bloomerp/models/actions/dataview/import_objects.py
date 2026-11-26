"""Import records for the model displayed by a dataview."""

from django.utils.translation import gettext_noop

from bloomerp.models.definition import DataviewAction, DataviewActionContext
from bloomerp.permissions.definition import BloomerpPermission


def dataview_import_button_attrs(
    context: DataviewActionContext,
) -> dict[str, str | None]:
    """Link to the model's import page when the user can open it."""
    from django.urls import NoReverseMatch, reverse

    from bloomerp.permissions.manager import UserPolicyManager
    from bloomerp.utils.models import get_bulk_upload_view_url

    if not UserPolicyManager(context.request.user).has_global_permission(
        context.model, BloomerpPermission.IMPORT
    ):
        return {"href": None}
    try:
        return {"href": reverse(get_bulk_upload_view_url(context.model))}
    except NoReverseMatch:
        return {"href": None}


def import_action() -> DataviewAction:
    """Link to the model's bulk import page when permitted."""
    return DataviewAction(
        id="import",
        label=gettext_noop("Import"),
        icon="fa-solid fa-upload",
        method="GET",
        button_attrs=dataview_import_button_attrs,
    )
