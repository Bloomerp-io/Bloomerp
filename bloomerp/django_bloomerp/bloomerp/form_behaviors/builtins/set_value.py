from copy import deepcopy
from typing import Any

from django import forms

from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    CleanedConfigData,
    FieldValueUpdate,
)
from bloomerp.form_fields.one_to_many_field import OneToManyField
from bloomerp.form_fields.structured_value import serialize_form_value
from bloomerp.models.application_field import ApplicationField


def _set_value_form_field(target: ApplicationField | None) -> forms.Field:
    """Build an optional native value field or reject a non-editable target."""
    if target is None:
        raise forms.ValidationError("Select a target field first.")

    value_field = target.get_form_field()
    if value_field is None:
        raise forms.ValidationError("The selected target field cannot accept a value.")
    if isinstance(value_field, OneToManyField):
        return forms.JSONField(
            required=False,
            label=value_field.label,
            help_text="Supply the complete collection row array.",
        )
    value_field.required = False

    return value_field


def _clean_set_value_form(form: forms.Form) -> dict[str, Any]:
    """Reject structured input for scalar text fields before it is stringified."""
    cleaned_data = forms.Form.clean(form) or {}
    field = form.fields["value"]
    raw_value = form.data.get(form.add_prefix("value"))
    if (
        isinstance(field, forms.CharField)
        and not isinstance(field, forms.JSONField)
        and isinstance(raw_value, (dict, list, tuple, set))
    ):
        raise forms.ValidationError(
            "The selected target field requires a scalar value."
        )
    return cleaned_data


def set_value(
    context: BehaviorContext,
    config: CleanedConfigData,
) -> BehaviorResult:
    """Replace the target draft value with a detached configured value."""
    return BehaviorResult(
        values=(
            FieldValueUpdate(
                field=context.target_field,
                value=deepcopy(serialize_form_value(config["value"])),
            ),
        )
    )


SET_VALUE = BehaviorActionDefinition(
    id="set_value",
    label="Set value",
    description="Replace the target field value, including with an empty value.",
    requires_target_field=True,
    execute=set_value,
    config_form_factory=lambda target, listener: type(
        "SetValueForm",
        (forms.Form,),
        {"value": _set_value_form_field(target), "clean": _clean_set_value_form},
    ),
)
