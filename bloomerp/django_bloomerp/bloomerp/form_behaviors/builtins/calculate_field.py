"""Calculate a declared top-level target from numeric fields in its model."""

from __future__ import annotations

import ast
from typing import Any

from django import forms
from django.db.models import QuerySet
from django.http import HttpRequest

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
    calculation_target_fields,
    evaluate_expression,
    numeric_fields,
    parse_expression,
)
from bloomerp.form_behaviors.shared.write_policy import (
    WritePolicyField,
    should_write_value,
)
from bloomerp.models.application_field import ApplicationField


def calculate_field_config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Build a restricted formula form against the listener/target model fields."""
    owner_field = listener or target
    if owner_field is None:
        raise forms.ValidationError("Select a listener and target field first.")
    sources = numeric_fields(owner_field.get_model())

    class CalculateFieldForm(forms.Form):
        """Configure top-level arithmetic and target overwrite behavior."""

        expression = forms.CharField(
            max_length=500,
            help_text="Use numeric field names with +, -, *, /, and parentheses.",
        )
        write_policy = WritePolicyField(
            allowed=("always", "if_empty", "if_empty_or_zero"),
            default="always",
        )

        def clean(self) -> dict[str, Any]:
            """Resolve expression names to permission-aware numeric source fields."""
            cleaned = super().clean()
            expression = cleaned.get("expression")
            if not expression:
                return cleaned
            try:
                parsed, names = parse_expression(expression)
            except forms.ValidationError as error:
                self.add_error("expression", error)
                return cleaned
            fields_by_name = {
                field.field: field for field in sources.filter(field__in=names)
            }
            unknown = sorted(set(names) - fields_by_name.keys())
            if unknown:
                self.add_error(
                    "expression",
                    f"Unknown or non-numeric field: {', '.join(unknown)}.",
                )
                return cleaned
            if target is not None and target.field in names:
                self.add_error(
                    "expression", "The target field cannot reference itself."
                )
                return cleaned
            cleaned["source_fields"] = {
                name: BehaviorFieldReference(field=fields_by_name[name])
                for name in names
            }
            cleaned["expression_tree"] = parsed
            return cleaned

    return CalculateFieldForm


def calculate_field_targets(
    fields: QuerySet[ApplicationField],
    listener: ApplicationField | None,
) -> QuerySet[ApplicationField]:
    """Offer property, numeric, and compatible character/text targets."""
    return calculation_target_fields(fields)


def calculate_field(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Evaluate top-level arithmetic and suggest the declared target update."""
    write_policy: str = config["write_policy"]
    if not should_write_value(context.target_value, write_policy):
        return BehaviorResult()
    expression_tree: ast.Expression = config["expression_tree"]
    result = evaluate_expression(expression_tree, context.values, operand_noun="Field")
    if context.target_value == result:
        return BehaviorResult()
    return BehaviorResult(
        values=(FieldValueUpdate(field=context.target_field, value=result),)
    )


CALCULATE_FIELD = BehaviorActionDefinition(
    id="calculate_field",
    label="Calculate field",
    description="Calculate a target from numeric fields on the current object.",
    requires_target_field=True,
    execute=calculate_field,
    config_form_factory=calculate_field_config_form_factory,
    get_target_fields=calculate_field_targets,
)
