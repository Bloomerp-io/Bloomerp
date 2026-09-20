from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorResult,
    FieldStateUpdate,
)


SHOW_FIELD = BehaviorActionDefinition(
    id="show_field",
    label="Show field",
    description="Show the target field without clearing its value.",
    requires_target_field=True,
    execute=lambda ctx, config: BehaviorResult(
        states=(
            FieldStateUpdate(field=ctx.target_field, visible=True), 
        )
    )
)
