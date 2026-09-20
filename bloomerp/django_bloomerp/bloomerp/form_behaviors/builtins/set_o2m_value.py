"""Update a column in matching rows of a collection's public value.

This action understands the O2M field schema (list of dictionaries), not its
widget. Matching is explicit and updates ALL matching rows. For one specific
unsaved row, match a stable draft key supplied by the future form-state layer.
"""

from copy import deepcopy

from django import forms

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorResult,
    FieldValueUpdate,
)
from bloomerp.models.application_field import ApplicationField


class SetO2MValueForm(forms.Form):
    match_column = forms.CharField(help_text="Column used to select rows.")
    match_value = forms.JSONField(required=False)
    target_column = forms.CharField(help_text="Column to update in matching rows.")
    value = forms.JSONField(required=False)


def collection_rows(value):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise forms.ValidationError("Expected a list of row dictionaries.")
    return deepcopy(value)


def set_o2m_value(context, config):
    if config["target_column"] in {"id", "DELETE"}:
        raise forms.ValidationError("Row identity and deletion are not value columns.")
    rows = collection_rows(context.target_value)
    changed = False
    for row in rows:
        if row.get("DELETE") in (True, "true", "True", "1", "on", "yes"):
            continue
        if (
            config["match_column"] in row
            and row[config["match_column"]] == config["match_value"]
            and row.get(config["target_column"]) != config["value"]
        ):
            row[config["target_column"]] = deepcopy(config["value"])
            changed = True
    if not changed:
        return BehaviorResult()
    return BehaviorResult(
        values=(FieldValueUpdate(field=context.target_field, value=rows),)
    )


SET_O2M_VALUE = BehaviorActionDefinition(
    id="set_o2m_value",
    label="Set related-row value",
    description="Set a column in every matching active row; preserve other values.",
    requires_target_field=True,
    execute=set_o2m_value,
    config_form_factory=lambda target, listener: type(
        "SetO2MValueForm",
        (forms.Form, ),
        {
            "from_column" : forms.ChoiceField(
                choices=[
                    (field.field, field.title)
                    for field in ApplicationField.get_for_model(target.get_model()).exclude(
                        field_type__in=[
                            FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id,
                        ]
                    )
                ]
            ),
            "to_column" : forms.ChoiceField(
                choices=[
                    (field.field, field.title)
                    for field in ApplicationField.get_for_model(target.get_model()).exclude(
                        field_type__in=[
                            FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id,
                        ]
                    )
                ]
            )
        }    
    ),
    get_target_fields=lambda fields, _: fields.filter(
        field_type=FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id
    )
)
