"""Resolve built-in and model-defined actions for each record surface."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import TYPE_CHECKING

from .builtins import get_default_object_actions

if TYPE_CHECKING:
    from django.db.models import Model

    from bloomerp.models.definition import (
        ObjectActionDefinition,
        ObjectActionGrouping,
        ObjectActionSurface,
    )


def iter_object_actions(
    actions: Sequence[ObjectActionDefinition],
    *,
    include_group: Callable[[ObjectActionGrouping], bool] | None = None,
) -> Iterator[ObjectActionDefinition]:
    """Yield actions in display order, skipping groups excluded by the predicate."""
    from bloomerp.models.definition import ObjectActionGrouping

    for action in actions:
        is_group = isinstance(action, ObjectActionGrouping)
        if is_group and include_group is not None and not include_group(action):
            continue
        yield action
        if is_group:
            yield from iter_object_actions(action.actions, include_group=include_group)


def get_object_actions(
    model: type[Model],
    *,
    surface: ObjectActionSurface,
    group_all: bool = False,
) -> list[ObjectActionDefinition]:
    """Resolve built-ins and model overrides for an object action surface."""
    from bloomerp.models.definition import ObjectActionGrouping, get_model_config

    from .sidebar import detail_only

    config = get_model_config(model)
    configured = config.object_actions if config else get_default_object_actions
    actions = configured(model) if callable(configured) else configured
    if surface == "detail":
        return actions
    actions = [
        action for action in actions if action.should_render_func is not detail_only
    ]
    if group_all:
        return (
            [ObjectActionGrouping(id="more-actions", actions=actions)]
            if actions
            else []
        )
    grouped_ids = {"create-todo", "contact"}
    grouped = [action for action in actions if action.id in grouped_ids]
    if grouped:
        return [
            ObjectActionGrouping(id="more-actions", actions=grouped),
            *(action for action in actions if action.id not in grouped_ids),
        ]
    return actions
