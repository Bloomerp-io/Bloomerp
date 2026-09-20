from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldStateUpdate,
)


def show_field(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Show the declared target without changing its current value."""
    return BehaviorResult(
        states=(FieldStateUpdate(field=context.target_field, visible=True),)
    )


SHOW_FIELD = BehaviorActionDefinition(
    id="show_field",
    label="Show field",
    description="Show the target field without clearing its value.",
    requires_target_field=True,
    execute=show_field,
)
