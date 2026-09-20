from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorResult,
    FieldStateUpdate,
)


def hide_field(context, config):
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
