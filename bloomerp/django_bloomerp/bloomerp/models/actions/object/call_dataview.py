"""Open a shared Data View from an object action."""

from collections.abc import Callable
from typing import Any

from django.db.models import Model

from bloomerp.filters.definition import Filters
from bloomerp.models.definition import (
    ActionDrawerSize,
    ObjectAction,
    ObjectActionContext,
    ObjectActionTarget,
)
from bloomerp.tokens import RequestToken, request_context_attributes

from ..shared import build_dataview_url
from .target import targeted_object_action


def call_dataview_action(
    id: str,
    model: type[Model],
    label: str,
    *,
    filters: Filters | Callable[[ObjectActionContext], Filters | None] | None = None,
    request_token: RequestToken | Callable[[ObjectActionContext], RequestToken | None] | None = None,
    title: str | None = None,
    size: ActionDrawerSize | None = None,
    should_render_func: Callable[[ObjectActionContext], bool] | None = None,
    target: ObjectActionTarget = "modal",
    body_class: str | None = None,
    icon: str | None = None,
) -> ObjectAction:
    """Open a dataview with optional filters and a request context for the source record."""

    def can_open(context: ObjectActionContext) -> bool:
        """Require sign-in for a token and apply the caller's visibility rule."""
        return (
            (request_token is None or context.request.user.is_authenticated)
            and (should_render_func is None or should_render_func(context))
        )

    def endpoint(context: ObjectActionContext) -> str:
        """Resolve the destination using the source record's filters."""
        resolved = filters(context) if callable(filters) else filters
        return build_dataview_url(model, filters=resolved, standalone=target == "main")

    def button_attrs(context: ObjectActionContext) -> dict[str, Any]:
        """Attach the optional context to the opening request."""
        token = request_token(context) if callable(request_token) else request_token
        return request_context_attributes(context.request, token) if token is not None else {}

    return targeted_object_action(
        target=target,
        id=id,
        endpoint=endpoint,
        label=label,
        icon=icon,
        button_attrs=button_attrs,
        should_render_func=can_open,
        title=title,
        size=size or ("lg" if target == "modal" else "md"),
        body_class=body_class,
    )
