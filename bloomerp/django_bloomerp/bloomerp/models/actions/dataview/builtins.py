"""Assemble and resolve the built-in dataview toolbar actions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.models import Model

    from bloomerp.models.definition import DataviewActionDefinition


def get_default_dataview_actions(
    model: type[Model],
    skip: Sequence[str] | None = None,
    include: Sequence[str] | None = None,
) -> list[DataviewActionDefinition]:
    """Return standard toolbar actions in display order, applying include before skip."""
    from .add import add_action
    from .bulk_actions import bulk_actions_group
    from .display_options import display_options_action
    from .export import export_action
    from .filter import filter_action
    from .import_export import import_export_group
    from .import_objects import import_action
    from .select_preference import select_preference_action

    transfer_actions: list[DataviewActionDefinition] = [import_action(), export_action()]
    if include is None or "import-export" in include:
        transfer_actions = [
            import_export_group([
                action for action in transfer_actions if not skip or action.id not in skip
            ])
        ]

    actions: list[DataviewActionDefinition] = [
        filter_action(),
        add_action(),
        bulk_actions_group(),
        *transfer_actions,
        display_options_action(),
        select_preference_action(),
    ]
    return [
        action
        for action in actions
        if (include is None or action.id in include)
        and (not skip or action.id not in skip)
    ]


def get_dataview_actions(model: type[Model]) -> list[DataviewActionDefinition]:
    """Resolve the model's configured toolbar list or call its action factory."""
    from bloomerp.models.definition import get_model_config

    config = get_model_config(model)
    view_settings = config.model_view_settings if config else None
    configured = (
        view_settings.dataview_actions
        if view_settings
        else get_default_dataview_actions
    )
    return configured(model) if callable(configured) else configured
