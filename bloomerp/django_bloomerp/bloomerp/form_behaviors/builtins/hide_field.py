from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldStateUpdate,
)


def hide_field(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Hide the declared target without changing its current value."""
    return BehaviorResult(
        states=(FieldStateUpdate(field=context.target_field, visible=False),)
    )


HIDE_FIELD = BehaviorActionDefinition(
    id="hide_field",
    label="Hide field",
    description="Hide the target field without clearing its value.",
    requires_target_field=True,
    execute=hide_field,
)
