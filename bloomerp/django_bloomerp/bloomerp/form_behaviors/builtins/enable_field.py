"""Enable interaction with a declared target while preserving its value."""

from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldStateUpdate,
)


def enable_field(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Return only the target's enabled state, leaving visibility unchanged."""
    return BehaviorResult(states=(FieldStateUpdate(
        field=context.target_field,
        disabled=False,
    ),))


ENABLE_FIELD = BehaviorActionDefinition(
    id="enable_field",
    label="Enable field",
    description="Allow interaction with the target without changing its value.",
    requires_target_field=True,
    execute=enable_field,
)
