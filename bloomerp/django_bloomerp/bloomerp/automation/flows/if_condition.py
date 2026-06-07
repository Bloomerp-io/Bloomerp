from dataclasses import dataclass
from typing import Any

from django import forms

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.schema import WorkflowInputRequirement, WorkflowIOSchema, WorkflowValueField
from bloomerp.automation.values import get_path_value


class IfConditionForm(forms.Form):
    field = forms.CharField(
        label="Field",
        help_text="Use a path on the incoming data, for example status or input.item.active.",
    )
    operator = forms.ChoiceField(
        choices=[
            ("exact", "Equals"),
            ("not_exact", "Does not equal"),
            ("contains", "Contains"),
            ("truthy", "Is truthy"),
            ("falsy", "Is falsy"),
        ],
        initial="exact",
    )
    value = forms.CharField(
        required=False,
        help_text="The value to compare against. Leave empty for truthy/falsy checks.",
    )


@dataclass
class BranchStopped:
    reason: str = "Condition did not match"


def _coerce_expected(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    if normalized == "none" or normalized == "null":
        return None
    return value


def _matches(value: Any, expected: Any, operator: str) -> bool:
    expected = _coerce_expected(expected)
    if operator == "not_exact":
        return str(value) != str(expected)
    if operator == "contains":
        return str(expected) in str(value)
    if operator == "truthy":
        return bool(value)
    if operator == "falsy":
        return not bool(value)
    return str(value) == str(expected)


def _resolve_field_value(input_data: Any, field: str) -> Any:
    if field.startswith("input."):
        return get_path_value({"input": input_data}, field)
    return get_path_value(input_data, field)


class IfConditionExecutor(BaseExecutor):
    config_form = IfConditionForm
    input_requirement = WorkflowInputRequirement(
        kind="any",
        label="Any input",
        description="Checks a condition against the incoming data.",
    )
    output_schema = WorkflowIOSchema(
        kind="object",
        label="Condition matched input",
        description="The original input continues downstream only when the condition is true.",
        fields=[
            WorkflowValueField("input", "Original Input", "object"),
        ],
    )

    @classmethod
    def get_output_schema(
        cls,
        config: dict | None = None,
        input_schema: WorkflowIOSchema | None = None,
    ) -> WorkflowIOSchema:
        if input_schema and input_schema.kind != "none":
            return WorkflowIOSchema(
                kind=input_schema.kind,
                label=f"Condition matched {input_schema.label or 'input'}",
                description="The original input continues downstream only when the condition is true.",
                fields=input_schema.fields,
            )
        return cls.output_schema

    def execute(self, input_data: Any) -> Any:
        params = self.resolve_config(input_data if isinstance(input_data, dict) else {"input": input_data})
        field = params.get("field")
        operator = params.get("operator", "exact")
        expected = params.get("value")

        if not field:
            return BranchStopped("No condition field configured")

        value = _resolve_field_value(input_data, field)
        if _matches(value, expected, operator):
            return input_data

        return BranchStopped(f"{field} did not match {operator} {expected}")
