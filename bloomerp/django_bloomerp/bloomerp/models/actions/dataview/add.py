"""Add a record from the dataview toolbar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.translation import gettext_noop

from bloomerp.permissions.definition import BloomerpPermission

if TYPE_CHECKING:
    from bloomerp.models.definition import DataviewAction, DataviewActionContext


def can_create_dataview_object(context: DataviewActionContext) -> bool:
    """Enable Add only when the model exposes a create route and the user has add permission."""
    from django.urls import NoReverseMatch, reverse

    from bloomerp.permissions.manager import UserPolicyManager
    from bloomerp.utils.models import get_create_view_url

    if context.create_url is not None:
        return True
    if not UserPolicyManager(context.request.user).has_global_permission(
        context.model, BloomerpPermission.ADD
    ):
        return False
    try:
        reverse(get_create_view_url(context.model))
    except NoReverseMatch:
        return False
    return True


def add_action() -> DataviewAction:
    """Open the shared add-record control when the viewer can create a record."""
    from bloomerp.models.definition import DataviewAction

    return DataviewAction(
        id="add",
        label=gettext_noop("Add"),
        icon="fa fa-plus",
        should_render_func=can_create_dataview_object,
        button_attrs={"data-dataview-create-button": "true", "hx-headers": '{"X-Request-Token": "xyz"}'},
        shortcut="mod+2",
    )
