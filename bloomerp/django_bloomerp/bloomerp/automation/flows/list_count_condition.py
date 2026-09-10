from typing import Any

from django import forms

from bloomerp.automation.base_executor import BaseExecutor, NodeExecutionError
from bloomerp.automation.ports import WorkflowNodeOutputPort
from bloomerp.automation.results import RouteResult
from bloomerp.automation.schema import (
    WorkflowIOFlowKind,
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueField,
)
from bloomerp.automation.values import get_path_value


class ListCountConditionForm(forms.Form):
    field = forms.CharField(
        label="Field",
        help_text="Use a path on the incoming data, for example status or input.item.list.",
    )
    operator = forms.ChoiceField(
        choices=[
            ("exact", "Equals"),
            ("not_exact", "Does not equal"),
            ("greater_than", "Greater than"),
            ("less_than", "Less than"),
            ("greater_than_or_equal", "Greater than or equal to"),
            ("less_than_or_equal", "Less than or equal to"),
        ],
        initial="exact",
    )
    value = forms.IntegerField(
        required=True,
        help_text="The value to compare against.",
    )


SUPPORTED_OPERATORS = {
    "exact",
    "not_exact",
    "greater_than",
    "less_than",
    "greater_than_or_equal",
    "less_than_or_equal",
}


def _resolve_field_value(input_data: Any, field: str) -> Any:
    if field == "input":
        return input_data
    if field.startswith("input."):
        return get_path_value({"input": input_data}, field)
    return get_path_value(input_data, field)


def _get_list_count(value: Any, field: str) -> int:
    if isinstance(value, (list, tuple)):
        return len(value)

    if hasattr(value, "all") and callable(value.all):
        collection = value.all()
        try:
            return len(collection)
        except TypeError:
            pass

    raise NodeExecutionError(
        f"Condition field '{field}' must resolve to a list-like value"
    )


def _coerce_expected_count(expected: Any) -> int:
    if isinstance(expected, bool):
        raise NodeExecutionError("Comparison value must be an integer")

    if isinstance(expected, int):
        return expected

    if isinstance(expected, str):
        try:
            return int(expected.strip())
        except ValueError:
            pass

    raise NodeExecutionError("Comparison value must be an integer")


def _matches(count: int, expected: int, operator: str) -> bool:
    if operator not in SUPPORTED_OPERATORS:
        raise NodeExecutionError(f"Unsupported list count operator '{operator}'")
    if operator == "exact":
        return count == expected
    if operator == "not_exact":
        return count != expected
    if operator == "greater_than":
        return count > expected
    if operator == "less_than":
        return count < expected
    if operator == "greater_than_or_equal":
        return count >= expected
    return count <= expected

class ListCountConditionExecutor(BaseExecutor):
    config_form = ListCountConditionForm
    output_ports = (
        WorkflowNodeOutputPort("true", "True", max_connections=None),
        WorkflowNodeOutputPort("false", "False", max_connections=None),
    )
    input_requirement = WorkflowInputRequirement(
        value_type="any",
        label="Any input",
        description="Checks a condition against the incoming data.",
    )
    output_schema = WorkflowIOSchema(
        value_type="object",
        flow_kind=WorkflowIOFlowKind.CONDITION_GATE,
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
        port_id: str = "default",
    ) -> WorkflowIOSchema:
        if input_schema and input_schema.value_type != "none":
            return WorkflowIOSchema(
                value_type=input_schema.value_type,
                flow_kind=WorkflowIOFlowKind.CONDITION_GATE,
                label=f"Condition matched {input_schema.label or 'input'}",
                description="The original input continues downstream only when the condition is true.",
                fields=input_schema.fields,
            )
        return cls.output_schema

    def execute(self, input_data: Any) -> RouteResult:
        params = self.resolve_config(
            input_data if isinstance(input_data, dict) else {"input": input_data}
        )
        field = params.get("field")
        operator = params.get("operator", "exact")
        expected = params.get("value")

        if not field:
            raise NodeExecutionError("No condition field configured")

        value = _resolve_field_value(input_data, field)
        count = _get_list_count(value, field)
        expected_count = _coerce_expected_count(expected)

        return RouteResult(
            port_id="true" if _matches(count, expected_count, operator) else "false",
            output=input_data,
        )
