from collections.abc import Callable
from typing import Literal

from bloomerp.models.definition import ObjectAction, ObjectActionContext


def detail_only(context: ObjectActionContext) -> bool:
    """Restrict an action to the object detail surface."""
    return context.surface == "detail"


def sidebar_action(
    *,
    id: str,
    endpoint: str | Callable[[ObjectActionContext], str],
    label: str | None = None,
    icon: str | None = None,
    remembered_view: Literal["activity", "comments"] | None = None,
) -> ObjectAction:
    """Load a fragment into the object detail sidebar and optionally remember its view."""
    return ObjectAction(
        id=id,
        label=label,
        icon=icon,
        method="GET",
        endpoint=endpoint,
        should_render_func=detail_only,
        button_attrs={
            "class": "btn btn-secondary btn-sm",
            "hx-target": "#object-sidesection",
            "hx-animation": True,
            **({"data-detail-sidebar-view": remembered_view} if remembered_view else {}),
        },
    )
