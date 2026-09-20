"""Assign sequential values to blank cells in a collection column."""

from django import forms
from django.db.models import QuerySet

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.form_behaviors.builtins.set_o2m_value import collection_rows
from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    CleanedConfigData,
    FieldValueUpdate,
)
from bloomerp.models.application_field import ApplicationField


def increment_o2m_value_config_form_factory(
    target: ApplicationField | None, listener: ApplicationField | None,
) -> type[forms.Form]:
    """Build the integer-column selector for the chosen collection listener."""
    if listener is None or listener.get_related_model() is None:
        raise forms.ValidationError("Select a collection listener first.")

    return type(
        "IncrementO2MValueForm",
        (forms.Form,),
        {
            "field": forms.ModelChoiceField(
                queryset=ApplicationField.get_for_model(
                    listener.get_related_model()
                ).filter(field_type=FIELD_TYPE_REGISTRY.INTEGER_FIELD.id)
            )
        },
    )


def increment_o2m_value(
    context: BehaviorContext, config: CleanedConfigData,
) -> BehaviorResult:
    """Fill blank active rows after the highest existing integer without mutating drafts."""
    rows = collection_rows(context.listener_value)
    if not rows:
        return BehaviorResult()

    column: ApplicationField = config["field"]
    active_rows = [
        row for row in rows
        if row.get("DELETE") not in (True, "true", "True", "1", "on", "yes")
    ]
    current_values = [
        value
        for row in active_rows
        if type(value := row.get(column.field)) is int
    ]
    next_value = max(current_values, default=0) + 1
    changed = False
    for row in active_rows:
        if row.get(column.field) in (None, ""):
            row[column.field] = next_value
            next_value += 1
            changed = True

    return (
        BehaviorResult(
            values=(FieldValueUpdate(field=context.listener_field, value=rows),)
        )
        if changed
        else BehaviorResult()
    )


def increment_o2m_listener_fields(
    fields: QuerySet[ApplicationField],
) -> QuerySet[ApplicationField]:
    """Limit this action to fields exposing one-to-many draft rows."""
    return fields.filter(field_type=FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id)


INCREMENT_O2M_VALUE = BehaviorActionDefinition(
    id="increment_o2m_value",
    label="Increment o2m value",
    description="Fill blank integer cells in a collection with sequential values.",
    config_form_factory=increment_o2m_value_config_form_factory,
    get_listener_fields=increment_o2m_listener_fields,
    execute=increment_o2m_value,
    requires_target_field=False,
)
