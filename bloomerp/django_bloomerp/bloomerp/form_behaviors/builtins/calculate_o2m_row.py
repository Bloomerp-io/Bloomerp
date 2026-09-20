"""Calculate one numeric destination for every active one-to-many row."""

from __future__ import annotations

import ast
from typing import Any

from django import forms
from django.db.models import QuerySet
from django.http import HttpRequest

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.form_behaviors.builtins.set_o2m_value import collection_rows
from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorFieldReference,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldValueUpdate,
)
from bloomerp.form_behaviors.shared.calculate import (
    clean_numeric_destination,
    evaluate_expression,
    numeric_fields,
    parse_expression,
)
from bloomerp.form_behaviors.shared.write_policy import (
    WritePolicyField,
    should_write_value,
)
from bloomerp.models.application_field import ApplicationField


def calculate_o2m_row_config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Build destination and expression fields for a collection listener."""
    if listener is None or listener.get_related_model() is None:
        raise forms.ValidationError("Select a collection listener first.")
    columns = numeric_fields(listener.get_related_model())

    class CalculateO2MRowForm(forms.Form):
        """Select a numeric destination and define its row arithmetic."""

        destination = forms.ModelChoiceField(
            queryset=columns,
            label="Destination column",
        )
        expression = forms.CharField(
            max_length=500,
            help_text="Use numeric column names with +, -, *, /, and parentheses.",
        )
        write_policy = WritePolicyField(
            allowed=("always", "if_empty", "if_empty_or_zero"),
            default="always",
        )

        def clean(self) -> dict[str, Any]:
            """Resolve every expression name to an eligible child ApplicationField."""
            cleaned = super().clean()
            destination = cleaned.get("destination")
            expression = cleaned.get("expression")
            if destination is None or not expression:
                return cleaned
            try:
                parsed, names = parse_expression(expression)
            except forms.ValidationError as error:
                self.add_error("expression", error)
                return cleaned
            fields_by_name = {
                field.field: field for field in columns.filter(field__in=names)
            }
            unknown = sorted(set(names) - fields_by_name.keys())
            if unknown:
                self.add_error(
                    "expression",
                    f"Unknown or non-numeric column: {', '.join(unknown)}.",
                )
                return cleaned
            if destination.field in names:
                self.add_error(
                    "expression",
                    "The destination column cannot reference itself.",
                )
                return cleaned
            cleaned["destination"] = BehaviorFieldReference(
                field=destination,
                permission="change",
            )
            cleaned["source_fields"] = {
                name: BehaviorFieldReference(field=fields_by_name[name])
                for name in names
            }
            cleaned["expression_tree"] = parsed
            return cleaned

    return CalculateO2MRowForm


def calculate_o2m_row(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Calculate the configured destination for every non-deleted listener row."""
    rows = collection_rows(context.listener_value)
    if not rows:
        return BehaviorResult()
    destination_reference: BehaviorFieldReference = config["destination"]
    destination = destination_reference.field
    expression_tree: ast.Expression = config["expression_tree"]
    write_policy: str = config["write_policy"]
    changed = False
    for row in rows:
        if row.get("DELETE") in (True, "true", "True", "1", "on", "yes"):
            continue
        if not should_write_value(
            row.get(destination.field), write_policy, field=destination
        ):
            continue
        result = clean_numeric_destination(
            destination, evaluate_expression(expression_tree, row)
        )
        if row.get(destination.field) != result:
            row[destination.field] = result
            changed = True
    if not changed:
        return BehaviorResult()
    return BehaviorResult(
        values=(FieldValueUpdate(field=context.listener_field, value=rows),)
    )


def calculate_o2m_row_listener_fields(
    fields: QuerySet[ApplicationField],
) -> QuerySet[ApplicationField]:
    """Limit row calculation to one-to-many listener fields."""
    return fields.filter(field_type=FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id)


CALCULATE_O2M_ROW = BehaviorActionDefinition(
    id="calculate_o2m_row",
    label="Calculate one-to-many row",
    description="Calculate a numeric destination column for every active collection row.",
    requires_target_field=False,
    execute=calculate_o2m_row,
    config_form_factory=calculate_o2m_row_config_form_factory,
    get_listener_fields=calculate_o2m_row_listener_fields,
)
