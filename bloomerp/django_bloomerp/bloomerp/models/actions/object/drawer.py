from collections.abc import Callable
from typing import Any

from bloomerp.models.definition import ObjectAction, ObjectActionContext


def drawer_action(
    *,
    id: str,
    endpoint: str | Callable[[ObjectActionContext], str],
    label: str | None = None,
    icon: str | None = None,
    drawer_id: str = "bloomerp-general-use-drawer",
    button_attrs: dict[str, Any] | Callable[[ObjectActionContext], dict[str, Any]] | None = None,
    should_render_func: Callable[[ObjectActionContext], bool] | None = None,
) -> ObjectAction:
    """Load a fragment into the shared drawer or a drawer with a custom ID."""
    def get_button_attrs(context: ObjectActionContext) -> dict[str, Any]:
        """Combine the drawer attributes with fixed or context-specific overrides."""
        overrides = button_attrs(context) if callable(button_attrs) else button_attrs
        return {
            "hx-target": f"#{drawer_id}-body",
            "bloomerp-open-drawer": drawer_id,
            **(overrides or {}),
        }

    return ObjectAction(
        id=id,
        endpoint=endpoint,
        label=label,
        icon=icon,
        method="GET",
        button_attrs=get_button_attrs,
        **({"should_render_func": should_render_func} if should_render_func is not None else {}),
    )
