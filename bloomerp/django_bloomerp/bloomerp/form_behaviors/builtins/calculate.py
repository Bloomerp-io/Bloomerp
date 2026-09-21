"""Calculate scalar fields or numeric columns using a restricted formula language."""

from __future__ import annotations

import ast
from decimal import Decimal, DecimalException
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
    MAX_EXPRESSION_NODES,
    calculation_target_fields,
    clean_numeric_destination,
    decimal_value,
    numeric_fields,
)
from bloomerp.form_behaviors.shared.write_policy import (
    WritePolicyField,
    should_write_value,
)
from bloomerp.models.application_field import ApplicationField

AGGREGATES = frozenset({"sum", "count", "first", "last"})
DELETED = (True, "true", "True", "1", "on", "yes")


def _inspect(
    node: ast.AST,
    names: set[str],
    columns: set[tuple[str, str]],
    *,
    aggregate: bool = False,
    row_mode: bool = False,
) -> None:
    """Validate formula syntax and collect scalar and collection references."""
    if isinstance(node, ast.Expression):
        _inspect(node.body, names, columns, aggregate=aggregate, row_mode=row_mode)
    elif isinstance(node, ast.Name):
        if aggregate:
            raise forms.ValidationError(
                "Aggregations must reference a collection column."
            )
        names.add(node.id)
    elif isinstance(node, ast.Attribute):
        if not isinstance(node.value, ast.Name) or (not aggregate and not row_mode):
            raise forms.ValidationError(
                "Collection columns must be used inside an aggregation."
            )
        columns.add((node.value.id, node.attr))
    elif isinstance(node, ast.Call):
        if (
            row_mode
            or aggregate
            or not isinstance(node.func, ast.Name)
            or node.func.id not in AGGREGATES
            or len(node.args) != 1
            or node.keywords
        ):
            raise forms.ValidationError(
                "Use sum, count, first, or last with one collection expression."
            )
        if node.func.id != "sum" and not isinstance(node.args[0], ast.Attribute):
            raise forms.ValidationError(
                "Count, first, and last require one collection column."
            )
        aggregate_columns: set[tuple[str, str]] = set()
        _inspect(node.args[0], names, aggregate_columns, aggregate=True)
        if not aggregate_columns:
            raise forms.ValidationError(
                "An aggregation must reference a collection column."
            )
        columns.update(aggregate_columns)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise forms.ValidationError(
                "Expressions may contain only numeric literals."
            )
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            raise forms.ValidationError(
                "Expressions support only +, -, *, and / operators."
            )
        _inspect(node.left, names, columns, aggregate=aggregate, row_mode=row_mode)
        _inspect(node.right, names, columns, aggregate=aggregate, row_mode=row_mode)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub)):
            raise forms.ValidationError("Expressions support only unary + and -.")
        _inspect(node.operand, names, columns, aggregate=aggregate, row_mode=row_mode)
    else:
        raise forms.ValidationError("Unsupported expression syntax.")


def _parse(
    expression: str, *, row_mode: bool
) -> tuple[ast.Expression, set[str], set[tuple[str, str]]]:
    """Parse a bounded formula and retain exact decimal literal values."""
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError) as error:
        raise forms.ValidationError("Enter a valid arithmetic expression.") from error
    if sum(1 for _ in ast.walk(tree)) > MAX_EXPRESSION_NODES:
        raise forms.ValidationError("The expression is too complex.")
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            literal = ast.get_source_segment(expression, node)
            try:
                node._bloomerp_decimal_value = Decimal((literal or "").replace("_", ""))
            except DecimalException as error:
                raise forms.ValidationError(
                    "Expressions require decimal numeric literals."
                ) from error
    names: set[str] = set()
    columns: set[tuple[str, str]] = set()
    _inspect(tree, names, columns, row_mode=row_mode)
    return tree, names, columns


def _evaluate(
    node: ast.AST, values: dict[str, Any], row: dict[str, Any] | None = None
) -> Decimal | None:
    """Evaluate only validated arithmetic and collection operations on draft values."""
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, values, row)
    if isinstance(node, ast.Name):
        return decimal_value(values.get(node.id), node.id, noun="Field")
    if isinstance(node, ast.Attribute):
        if row is None:
            raise forms.ValidationError("A collection row is required.")
        return decimal_value(row.get(node.attr), node.attr)
    if isinstance(node, ast.Constant):
        return decimal_value(
            getattr(node, "_bloomerp_decimal_value", node.value), "literal"
        )
    if isinstance(node, ast.Call):
        collection = node.args[0]
        collection_name = next(
            part.value.id
            for part in ast.walk(collection)
            if isinstance(part, ast.Attribute)
        )
        rows = [
            item
            for item in collection_rows(values.get(collection_name))
            if item.get("DELETE") not in DELETED
        ]
        evaluated = [
            _evaluate(collection, values, item)
            for item in rows
            if not (
                isinstance(collection, ast.Attribute)
                and item.get(collection.attr) in (None, "")
            )
        ]
        if node.func.id == "count":
            return Decimal(len(evaluated))
        if node.func.id == "sum":
            return sum((item or Decimal(0) for item in evaluated), Decimal(0))
        if not evaluated:
            return None
        return evaluated[0] if node.func.id == "first" else evaluated[-1]
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate(node.operand, values, row) or Decimal(0)
        return operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left, values, row) or Decimal(0)
        right = _evaluate(node.right, values, row) or Decimal(0)
        try:
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise forms.ValidationError("The expression divides by zero.")
            return left / right
        except DecimalException as error:
            raise forms.ValidationError(
                "The expression cannot be calculated."
            ) from error
    raise forms.ValidationError("Unsupported expression syntax.")


def calculate_config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Build a formula editor whose destination column appears only for O2M targets."""
    owner = listener or target
    if owner is None or target is None:
        raise forms.ValidationError("Select a listener and target field first.")
    row_mode = target.field_type == FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id
    parent_numeric = numeric_fields(owner.get_model())
    collections = ApplicationField.get_for_model(owner.get_model()).filter(
        field_type=FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id
    )
    if row_mode:
        layout_config = getattr(target, "_behavior_layout_config", {})
        rendered_ids = [
            column.pk
            for column in target.get_widget(layout_config=layout_config).get_columns()
        ]
        target_columns = numeric_fields(target.get_related_model()).filter(
            pk__in=rendered_ids
        )
    else:
        target_columns = ApplicationField.objects.none()

    class CalculateForm(forms.Form):
        """Configure the destination and safe formula for a calculation."""

        if row_mode:
            target_column = forms.ModelChoiceField(
                queryset=target_columns, label="Target column"
            )
        expression = forms.CharField(
            max_length=500,
            help_text="Use numeric fields, collection.column, and sum/count/first/last for scalar targets.",
        )
        write_policy = WritePolicyField(
            allowed=("always", "if_empty", "if_empty_or_zero"), default="always"
        )

        def clean(self) -> dict[str, Any]:
            """Resolve each operand to an eligible field before evaluating a draft."""
            cleaned = super().clean()
            expression = cleaned.get("expression")
            if not expression:
                return cleaned
            try:
                tree, names, columns = _parse(expression, row_mode=row_mode)
                parent_fields = {
                    field.field: field
                    for field in parent_numeric.filter(field__in=names)
                }
                if names - parent_fields.keys():
                    raise forms.ValidationError(
                        f"Unknown or non-numeric field: {', '.join(sorted(names - parent_fields.keys()))}."
                    )
                if not row_mode and target.field in names:
                    raise forms.ValidationError(
                        "The target field cannot reference itself."
                    )
                collection_fields = {field.field: field for field in collections}
                if row_mode and any(name != target.field for name, _ in columns):
                    raise forms.ValidationError(
                        "Row formulas may only reference the target collection."
                    )
                if len({name for name, _ in columns}) > 1:
                    raise forms.ValidationError(
                        "An expression may reference only one collection."
                    )
                child_fields: dict[tuple[str, str], ApplicationField] = {}
                for collection_name, column_name in columns:
                    collection_field = collection_fields.get(collection_name)
                    if (
                        collection_field is None
                        or collection_field.get_related_model() is None
                    ):
                        raise forms.ValidationError(
                            f"Unknown collection: {collection_name}."
                        )
                    child = (
                        numeric_fields(collection_field.get_related_model())
                        .filter(field=column_name)
                        .first()
                    )
                    if child is None:
                        raise forms.ValidationError(
                            f"Unknown or non-numeric column: {collection_name}.{column_name}."
                        )
                    child_fields[(collection_name, column_name)] = child
                destination = cleaned.get("target_column") if row_mode else None
                if (
                    row_mode
                    and destination is not None
                    and (target.field, destination.field) in columns
                ):
                    raise forms.ValidationError(
                        "The target column cannot reference itself."
                    )
                cleaned["source_fields"] = {
                    name: BehaviorFieldReference(field=field)
                    for name, field in parent_fields.items()
                }
                cleaned["collection_fields"] = {
                    name: BehaviorFieldReference(field=collection_fields[name])
                    for name, _ in columns
                }
                cleaned["column_fields"] = {
                    key: BehaviorFieldReference(field=field)
                    for key, field in child_fields.items()
                }
                cleaned["expression_tree"] = tree
            except forms.ValidationError as error:
                self.add_error("expression", error)
            return cleaned

    return CalculateForm


def calculate_targets(
    fields: QuerySet[ApplicationField], listener: ApplicationField | None
) -> QuerySet[ApplicationField]:
    """Offer scalar calculation targets and one-to-many collections."""
    scalar_ids = list(calculation_target_fields(fields).values_list("pk", flat=True))
    return fields.filter(pk__in=scalar_ids) | fields.filter(
        field_type=FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id
    )


def calculate(
    context: BehaviorContext, config: CleanedConfigData, user: BehaviorUser
) -> BehaviorResult:
    """Update a scalar target or calculate one destination column per active row."""
    tree: ast.Expression = config["expression_tree"]
    policy: str = config["write_policy"]
    if "target_column" not in config:
        if not should_write_value(context.target_value, policy):
            return BehaviorResult()
        result = _evaluate(tree, dict(context.values))
        if context.target_value == result:
            return BehaviorResult()
        return BehaviorResult(
            values=(FieldValueUpdate(field=context.target_field, value=result),)
        )
    destination: ApplicationField = config["target_column"]
    rows = collection_rows(context.target_value)
    changed = False
    for row in rows:
        if row.get("DELETE") in DELETED or not should_write_value(
            row.get(destination.field), policy, field=destination
        ):
            continue
        result = clean_numeric_destination(
            destination, _evaluate(tree, dict(context.values), row) or Decimal(0)
        )
        if row.get(destination.field) != result:
            row[destination.field] = result
            changed = True
    if not changed:
        return BehaviorResult()
    return BehaviorResult(
        values=(FieldValueUpdate(field=context.target_field, value=rows),)
    )


CALCULATE = BehaviorActionDefinition(
    id="calculate",
    label="Calculate",
    description="Calculate a field or a column in every collection row from a safe numeric formula.",
    requires_target_field=True,
    execute=calculate,
    config_form_factory=calculate_config_form_factory,
    get_target_fields=calculate_targets,
)
