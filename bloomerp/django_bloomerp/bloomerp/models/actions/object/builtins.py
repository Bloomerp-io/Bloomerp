from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.models import Model

    from bloomerp.models.definition import ObjectActionDefinition


def get_default_object_actions(
    model: type[Model],
    skip: Sequence[str] | None = None,
    include: Sequence[str] | None = None,
) -> list[ObjectActionDefinition]:
    """Return the model's built-in actions in display order, applying include before skip."""
    from bloomerp.models.actions.object.activity import activity_action
    from bloomerp.models.actions.object.comments import comments_action
    from bloomerp.models.actions.object.contact import contact_action
    from bloomerp.models.actions.object.create_todo import create_todo_action
    
    actions = [activity_action(), comments_action(), create_todo_action(model), contact_action(model)]
    return [
        action for action in actions
        if action is not None
        and (include is None or action.id in include)
        and (skip is None or action.id not in skip)
    ]
