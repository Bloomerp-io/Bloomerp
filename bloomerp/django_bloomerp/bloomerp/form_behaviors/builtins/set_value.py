from copy import deepcopy

from django import forms

from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorResult,
    FieldValueUpdate,
)


class SetValueForm(forms.Form):
    value = forms.JSONField(
        required=False,
        help_text='A value in the target field schema, e.g. "25.00", true or null.',
    )


def set_value(context, config):
    return BehaviorResult(
        values=(
            FieldValueUpdate(
                field=context.target_field, value=deepcopy(config["value"])
            ),
        )
    )


SET_VALUE = BehaviorActionDefinition(
    id="set_value",
    label="Set value",
    description="Replace the target field value, including with an empty value.",
    requires_target_field=True,
    execute=set_value,
    config_form_factory=lambda target, listener: SetValueForm,
)
