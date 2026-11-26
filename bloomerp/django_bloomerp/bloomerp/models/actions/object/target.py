"""Target record actions at the main content or a shared overlay."""

from collections.abc import Callable
from typing import Any

from bloomerp.models.definition import (
    ActionDrawerSize,
    ObjectAction,
    ObjectActionContext,
    ObjectActionTarget,
    ObjectDrawerAction,
    ObjectModalAction,
)

from ..shared import target_button_attrs


def targeted_object_action(
    *,
    target: ObjectActionTarget,
    id: str,
    endpoint: Callable[[ObjectActionContext], str],
    label: str,
    icon: str | None,
    should_render_func: Callable[[ObjectActionContext], bool],
    button_attrs: dict[str, Any] | Callable[[ObjectActionContext], dict[str, Any]] | None,
    title: str | None = None,
    size: ActionDrawerSize = "md",
    body_class: str | None = None,
) -> ObjectAction:
    """Build a GET action using Bloomerp's main content or shared overlay controls."""

    def get_button_attrs(context: ObjectActionContext) -> dict[str, Any]:
        """Apply the target's navigation defaults and then any caller overrides."""
        overrides = button_attrs(context) if callable(button_attrs) else button_attrs
        return target_button_attrs(main=target == "main", overrides=overrides)

    kwargs = {
        "id": id,
        "endpoint": endpoint,
        "label": label,
        "icon": icon,
        "should_render_func": should_render_func,
        "button_attrs": get_button_attrs,
    }
    match target:
        case "main":
            return ObjectAction(method="GET", **kwargs)
        case "modal":
            return ObjectModalAction(title=title, size=size, body_class=body_class, **kwargs)
        case "drawer":
            return ObjectDrawerAction(title=title, size=size, body_class=body_class, **kwargs)
        case _:
            raise ValueError(f"Invalid object action target: {target!r}")
