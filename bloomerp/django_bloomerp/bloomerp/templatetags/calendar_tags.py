"""Inbox-specific controls backed by the generic calendar grouping contract."""

from typing import Any

from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.dataviews.calendar.grouping import calendar_group_color
from django import template
from django.http import HttpRequest

register = template.Library()


@register.simple_tag
def inbox_calendar_overlay(request: HttpRequest) -> dict[str, Any]:
    """Offer only effective inboxes available to this user and restore the applied selection."""
    inboxes = list(accessible_inboxes(request.user).order_by("name", "pk"))
    query = request.GET
    raw = (
        query.get("calendar_color_values")
        or query.get("inboxes__in")
        or query.get("inboxes")
    )
    selected = set(raw.split(",")) if raw else {str(inbox.pk) for inbox in inboxes}
    preferred = query.get("calendar_color_preferred") or query.get("inboxes", "")
    return {
        "preferred": preferred,
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
