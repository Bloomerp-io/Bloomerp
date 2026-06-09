from dataclasses import dataclass
from typing import Any

from django import forms

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.schema import (
    WorkflowIOFlowKind,
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueField,
    remap_schema_field_paths,
)


class ForEachForm(forms.Form):
    pass


@dataclass
class ForEachResult:
    items: list
    collection: list


def normalize_items(input_data: Any) -> list:
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


class ForEachExecutor(BaseExecutor):
    config_form = ForEachForm
    input_requirement = WorkflowInputRequirement(
        value_type="list",
        label="Object list",
        description="Runs downstream nodes once for each item in a list.",
    )
    
    output_schema = WorkflowIOSchema(
        value_type="object",
        flow_kind=WorkflowIOFlowKind.FANOUT,
        label="Each item",
        description="Downstream nodes receive one item at a time.",
        fields=[
            WorkflowValueField("input.item", "Current Item", "object"),
            WorkflowValueField("input.index", "Current Index", "number"),
            WorkflowValueField("input.collection", "Original Collection", "list"),
        ],
    )

    @classmethod
    def get_output_schema(
        cls,
        config: dict | None = None,
        input_schema: WorkflowIOSchema | None = None,
    ) -> WorkflowIOSchema:
        if input_schema and input_schema.value_type == "list" and input_schema.fields:
            item_fields = [
                field for field in input_schema.fields
                if field.path == "input.0" or field.path.startswith("input.0.")
            ]
            return WorkflowIOSchema(
                value_type="object",
                flow_kind=WorkflowIOFlowKind.FANOUT,
                label=f"Each {input_schema.label or 'item'}",
                description="Downstream nodes receive one item at a time.",
                fields=[
                    WorkflowValueField(
                        "input.item",
                        "Current Item",
                        "object",
                        children=remap_schema_field_paths(item_fields, {"input.0": "input.item"}),
                    ),
                    WorkflowValueField("input.index", "Current Index", "number"),
                    WorkflowValueField("input.collection", "Original Collection", "list"),
                ],
            )
        
        return cls.output_schema

    def execute(self, input_data: Any) -> ForEachResult:
        items = normalize_items(input_data)
        return ForEachResult(items=items, collection=items)
