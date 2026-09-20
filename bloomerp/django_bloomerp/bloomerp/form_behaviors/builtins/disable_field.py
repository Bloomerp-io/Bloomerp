"""Disable interaction with a declared target while preserving its value."""

from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldStateUpdate,
)


def disable_field(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Return only the target's disabled state, leaving visibility unchanged."""
    return BehaviorResult(states=(FieldStateUpdate(
        field=context.target_field,
        disabled=True,
    ),))


DISABLE_FIELD = BehaviorActionDefinition(
    id="disable_field",
    label="Disable field",
    description="Prevent interaction with the target without changing its value.",
    requires_target_field=True,
    execute=disable_field,
)
