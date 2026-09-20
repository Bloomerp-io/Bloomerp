"""Aggregate one numeric collection column into a top-level target field."""

from decimal import Decimal

from django import forms

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.form_behaviors.builtins.set_o2m_value import collection_rows
from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    CleanedConfigData,
    FieldValueUpdate,
)
from bloomerp.form_behaviors.shared.calculate import decimal_value
from bloomerp.form_behaviors.shared.write_policy import (
    WritePolicyField,
    should_write_value,
)
from bloomerp.models.application_field import ApplicationField

aggregatable = [
    FIELD_TYPE_REGISTRY.INTEGER_FIELD.id,
    FIELD_TYPE_REGISTRY.DECIMAL_FIELD.id,
    FIELD_TYPE_REGISTRY.FLOAT_FIELD.id,
]


def aggregate_o2m_column(
    ctx: BehaviorContext, cleaned_dat: CleanedConfigData,
) -> BehaviorResult:
    """Aggregate nonblank values from active rows without mutating the draft."""
    write_policy: str = cleaned_dat["write_policy"]
    if not should_write_value(ctx.target_value, write_policy):
        return BehaviorResult()
    rows = collection_rows(ctx.listener_value)
    column: ApplicationField = cleaned_dat["column"]
    values = [
        decimal_value(row.get(column.field), column.field)
        for row in rows
        if row.get("DELETE")
        not in (True, "true", "True", "1", "on", "yes")
        and row.get(column.field) not in (None, "")
    ]
    aggregation_type = cleaned_dat["aggregation_type"]
    if aggregation_type == "sum":
        result: Decimal | int | None = sum(values, start=Decimal(0))
    elif aggregation_type == "count":
        result = len(values)
    elif aggregation_type == "first":
        result = values[0] if values else None
    elif aggregation_type == "last":
        result = values[-1] if values else None
    else:
        raise forms.ValidationError("Unknown aggregation type.")
    return BehaviorResult(
        values=(FieldValueUpdate(field=ctx.target_field, value=result),)
    )


AGGREGATE_O2M_COLUMN = BehaviorActionDefinition(
    id="aggregate_o2m_column",
    label="Aggregate o2m columns",
    description="Aggregate one-to-many columns into another field",
    get_listener_fields=lambda fields: fields.filter(
        field_type=FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id
    ),
    get_target_fields=lambda fields, _: fields.filter(
        field_type__in=[
            *aggregatable,
            FIELD_TYPE_REGISTRY.PROPERTY.id,
            FIELD_TYPE_REGISTRY.CHAR_FIELD.id,
        ]
    ),
    config_form_factory=lambda target, listener: type(
        "AggregateO2MColumn",
        (forms.Form, ),
        {
            "aggregation_type" : forms.ChoiceField(
                choices=[
                    ("sum", "Sum"),
                    ("count", "Count"),
                    ("first", "First"),
                    ("last", "Last"),
                ]
            ),
            "column" : forms.ModelChoiceField(
                queryset=ApplicationField.get_for_model(
                    listener.related_model.model_class()
                ).filter(
                    field_type__in=aggregatable
                )
            ),
            "write_policy": WritePolicyField(
                allowed=("always", "if_empty", "if_empty_or_zero"),
                default="always",
            ),
        }
    ),
    execute=aggregate_o2m_column,
    requires_target_field=True,
)
