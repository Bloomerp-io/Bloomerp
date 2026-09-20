from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorResult,
    FieldStateUpdate,
)


HIDE_FIELD = BehaviorActionDefinition(
    id="hide_field",
    label="Hide field",
    description="Hide the target field without clearing its value.",
    requires_target_field=True,
    execute=lambda ctx, _: BehaviorResult(
        states=(
            FieldStateUpdate(field=ctx.target_field, visible=False),
        )
    )
)
