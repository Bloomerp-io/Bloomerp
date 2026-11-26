"""Open a dataview from another dataview's toolbar."""

from collections.abc import Callable
from typing import Any

from django.db.models import Model

from bloomerp.filters.definition import Filters
from bloomerp.models.definition import (
    ActionDrawerSize,
    DataviewAction,
    DataviewActionContext,
    DataviewDrawerAction,
    DataviewModalAction,
    ObjectActionTarget,
)
from bloomerp.tokens import RequestToken, request_context_attributes

from ..shared import build_dataview_url, target_button_attrs


def call_dataview_action(
    id: str,
    model: type[Model],
    label: str,
    *,
    filters: Filters | Callable[[DataviewActionContext], Filters | None] | None = None,
    request_token: RequestToken | Callable[[DataviewActionContext], RequestToken | None] | None = None,
    title: str | None = None,
    size: ActionDrawerSize | None = None,
    should_render_func: Callable[[DataviewActionContext], bool] | None = None,
    target: ObjectActionTarget = "modal",
    body_class: str | None = None,
    icon: str | None = None,
) -> DataviewAction:
    """Open a dataview with optional initial filters and a request context."""

    def can_open(context: DataviewActionContext) -> bool:
        """Require sign-in for a token and apply the caller's visibility rule."""
        return (
            (request_token is None or context.request.user.is_authenticated)
            and (should_render_func is None or should_render_func(context))
        )

    def endpoint(context: DataviewActionContext) -> str:
        """Resolve the destination using the current dataview and selection."""
        resolved = filters(context) if callable(filters) else filters
        return build_dataview_url(model, filters=resolved, standalone=target == "main")

    def button_attrs(context: DataviewActionContext) -> dict[str, Any]:
        """Attach the optional context to the opening request."""
        token = request_token(context) if callable(request_token) else request_token
        headers = request_context_attributes(context.request, token) if token is not None else None
        return target_button_attrs(main=target == "main", overrides=headers)

    kwargs = {
        "id": id,
        "label": label,
        "icon": icon,
        "endpoint": endpoint,
        "should_render_func": can_open,
        "button_attrs": button_attrs,
        "forward_dataview_context": False,
    }
    match target:
        case "main":
            return DataviewAction(method="GET", **kwargs)
        case "modal":
            return DataviewModalAction(title=title, size=size or "lg", body_class=body_class, **kwargs)
        case "drawer":
            return DataviewDrawerAction(title=title, size=size or "2xl", body_class=body_class, **kwargs)
        case _:
            raise ValueError(f"Invalid dataview action target: {target!r}")
