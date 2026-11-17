"""Template presentation for the full Pages view and its compact scratchpad."""

from typing import Any
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

from bloomerp.models import Page
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


def page_context(request: HttpRequest) -> dict[str, Any]:
    """Use Page model queries for selection and all three navigation sections."""
    recent = Page.recent_for(request.user)
    page = None
    identifier = request.GET.get("page")
    if identifier:
        try:
            page = get_object_or_404(
                Page.accessible_to(request.user), pk=UUID(identifier)
            )
        except ValueError as error:
            raise Http404("Invalid page") from error
    elif request.GET.get("new") != "1":
        page = next(iter(recent), None)
    manage = page is None or page.can_manage(request.user)
    prefix = f"page_{uuid4().hex}"
    return {
        "page_sections": [
            (str(_("Recents")), recent),
            (str(_("Shared")), Page.shared_for(request.user)),
            (str(_("Private")), Page.private_for(request.user)),
        ],
        "page": page,
        "can_manage_page": manage,
        "page_version": page.datetime_updated.isoformat() if page else "",
        "page_title": page.title if page else "",
        "page_content": page.content if page else "",
        "sharing_user_widget": ForeignFieldWidget(
            model=get_user_model(), attrs={"is_m2m": True, "aria_label": _("Users")}
        ).render(f"{prefix}_users", page.shared_with_users.all() if page else [])
        if manage
        else "",
        "sharing_group_widget": ForeignFieldWidget(
            model=Group, attrs={"is_m2m": True, "aria_label": _("Groups")}
        ).render(f"{prefix}_groups", page.shared_with_groups.all() if page else [])
        if manage
        else "",
    }
