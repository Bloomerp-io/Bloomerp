"""Shared URL construction for actions that open a dataview."""

from typing import Any
from urllib.parse import urlencode

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.urls import reverse

from bloomerp.filters.definition import Filters
from bloomerp.filters.parser import serialize_filter_query_params


def target_button_attrs(
    *,
    main: bool,
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply the navigation defaults shared by record and toolbar actions."""
    defaults = (
        {"hx-target": "#main-content", "hx-push-url": "true"}
        if main
        else {"hx-push-url": "false"}
    )
    return {**defaults, **(overrides or {})}


def build_dataview_url(
    model: type[Model], *, filters: Filters | None, standalone: bool,
) -> str:
    """Address a standalone or embedded dataview with its initial filters."""
    from bloomerp.dataviews.definition import DATAVIEW_PAGE_PARAM

    content_type = ContentType.objects.get_for_model(model)
    url = reverse("components_dataview", kwargs={"content_type_id": content_type.pk})
    query = serialize_filter_query_params(filters, shorthand=True)
    if standalone:
        query[DATAVIEW_PAGE_PARAM] = "true"
    return f"{url}?{urlencode(query)}" if query else url
