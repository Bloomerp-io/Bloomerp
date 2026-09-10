from typing import Any

from django import forms

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.results import StopBranchResult
from bloomerp.automation.schema import (
    WorkflowIOFlowKind,
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueField,
    remap_schema_field_paths,
)
from bloomerp.automation.values import get_path_value, resolve_value


class FilterObjectsForm(forms.Form):
    field = forms.CharField(
        label="Field",
        help_text="Field name on each item, for example status.",
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
        help_text="Use a literal value or a reference such as {{ input.status }}.",
    )
    continue_on_empty = forms.BooleanField(
        required=False,
        initial=True,
        label="Continue when no objects match",
        help_text="When disabled, an empty filtered result stops this workflow branch.",
    )


def _normalize_collection(input_data: Any) -> list:
    if input_data is None:
        return []
    if isinstance(input_data, list):
        return input_data
    if hasattr(input_data, "all"):
        return list(input_data.all())
    if isinstance(input_data, dict):
        records = input_data.get("records")
        if isinstance(records, list):
            return records
        if hasattr(records, "all"):
            return list(records.all())
    return []


def _matches(value: Any, expected: Any, operator: str) -> bool:
    if operator == "not_exact":
        return str(value) != str(expected)
    if operator == "contains":
        return str(expected) in str(value)
    if operator == "truthy":
        return bool(value)
    if operator == "falsy":
        return not bool(value)
    return str(value) == str(expected)


class FilterObjectsExecutor(BaseExecutor):
    config_form = FilterObjectsForm
    input_requirement = WorkflowInputRequirement(
        value_type="list",
        label="Object list",
        description="Filters a list of objects from the previous node.",
    )
    output_schema = WorkflowIOSchema(
        value_type="list",
        label="Filtered objects",
        description="The subset of input objects that matched the filter.",
        fields=[
            WorkflowValueField("input", "Filtered Objects", "list"),
            WorkflowValueField("input.0", "First Filtered Object", "object"),
        ],
    )

    @classmethod
    def get_output_schema(
        cls,
        config: dict | None = None,
        input_schema: WorkflowIOSchema | None = None,
        port_id: str = "default",
    ) -> WorkflowIOSchema:
        flow_kind = (
            WorkflowIOFlowKind.CONDITION_GATE
            if config and config.get("continue_on_empty") is False
            else WorkflowIOFlowKind.NORMAL
        )
        if input_schema and input_schema.value_type == "list" and input_schema.fields:
            return WorkflowIOSchema(
                value_type="list",
                flow_kind=flow_kind,
                label=f"Filtered {input_schema.label or 'objects'}",
                description="The subset of upstream objects that matched the filter.",
                fields=remap_schema_field_paths(input_schema.fields, {}),
            )
        return WorkflowIOSchema(
            value_type=cls.output_schema.value_type,
            flow_kind=flow_kind,
            label=cls.output_schema.label,
            description=cls.output_schema.description,
            fields=remap_schema_field_paths(cls.output_schema.fields, {}),
        )

    def execute(self, input_data: Any) -> list | StopBranchResult:
        params = self.resolve_config(input_data if isinstance(input_data, dict) else {"records": input_data})
        field = params.get("field")
        operator = params.get("operator", "exact")
        expected = params.get("value")
        continue_on_empty = params.get("continue_on_empty", True)
        records = _normalize_collection(input_data)

        if not field:
            filtered_records = records
        else:
            filtered_records = [
                item
                for item in records
                if _matches(get_path_value(item, field), expected, operator)
            ]

        if not filtered_records and not continue_on_empty:
            return StopBranchResult(reason="No objects matched the filter")
        return filtered_records
