"""Inbox-specific controls backed by the generic calendar grouping contract."""

from typing import Any

from django import template
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext as _

from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.dataviews.calendar.grouping import calendar_group_color
from bloomerp.communication.calendar.access import calendar_overlay_selection
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

register = template.Library()


@register.simple_tag
def inbox_calendar_overlay(request: HttpRequest) -> dict[str, Any]:
    """Offer only effective inboxes available to this user and restore the applied selection."""
    inboxes = list(accessible_inboxes(request.user).order_by("name", "pk"))
    query = request.GET
    inbox_id = query.get("_arg_calendar_inbox")
    selection = (
        calendar_overlay_selection(request.user, int(inbox_id))
        if inbox_id and inbox_id.isdigit()
        else None
    )
    raw = (
        query.get("calendar_color_values")
        or query.get("inboxes__in")
        or query.get("inboxes")
    )
    selected = (
        set(selection["inboxes"])
        if selection
        else (set(raw.split(",")) if raw else {str(inbox.pk) for inbox in inboxes})
    )
    preferred = query.get("calendar_color_preferred") or query.get("inboxes", "")
    return {
        "preferred": preferred,
        "save_url": reverse("components_calendar_align", kwargs={"inbox_id": int(inbox_id)})
        if selection
        else "",
        "users_widget": ForeignFieldWidget(
            model=get_user_model(),
            attrs={
                "is_m2m": True,
                "class": "input w-full",
                "aria_label": _("Other users"),
            },
        ).render("calendar_overlay_users", selection["users"] if selection else []),
        "inboxes": [
            {
                "value": str(inbox.pk),
                "label": str(inbox),
                "selected": str(inbox.pk) in selected,
                "color_classes": calendar_group_color(str(inbox.pk), relation=True),
            }
            for inbox in inboxes
        ],
    }
