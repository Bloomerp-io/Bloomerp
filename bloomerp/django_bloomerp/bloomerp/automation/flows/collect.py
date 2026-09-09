from django import forms

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.results import DeferResult, PreparedInput
from bloomerp.automation.schema import (
    WorkflowIOFlowKind,
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueField,
    WorkflowValueType,
)


class CollectForm(forms.Form):
    pass


def _as_collected_item_field(field: WorkflowValueField) -> WorkflowValueField:
    if field.path == "input":
        path = "0"
    elif field.path.startswith("input."):
        path = f"0.{field.path.removeprefix('input.')}"
    else:
        path = f"0.{field.path}" if field.path else "0"

    return WorkflowValueField(
        path=path,
        label=field.label,
        value_type=field.value_type,
        description=field.description,
        optional=field.optional,
        children=[
            _as_collected_item_field(child)
            for child in field.children
        ],
    )


class CollectExecutor(BaseExecutor):
    """Collapse the current for-each fan-out into one ordered list."""

    config_form = CollectForm
    input_requirement = WorkflowInputRequirement(
        value_type=WorkflowValueType.ANY,
        label="Item result",
        description="Collects one result from each iteration of the current For Each.",
    )

    def execute(self, trigger_data):
        return trigger_data

    def prepare(self, input_data, context):
        if not context.scope_key:
            raise ValueError("Collect must run inside a fan-out branch.")

        fanout_node_id, item_index = context.scope_key[-1]
        parent_scope = context.scope_key[:-1]
        fanout_state = context.state.get_fanout_state(fanout_node_id, parent_scope)
        if fanout_state is None:
            raise ValueError("Collect could not find its parent fan-out state.")

        collect_state = context.state.get_collect_state(
            context.node.id,
            fanout_node_id,
            parent_scope,
        )
        if collect_state.released:
            return DeferResult(consume_sequence=False)

        context.set_transient_output("collect", parent_scope, item_index, input_data)
        collected_outputs = {}
        for index in range(fanout_state.item_count):
            found, output = context.get_transient_output(
                "collect",
                parent_scope,
                index,
            )
            if found:
                collected_outputs[index] = output

        waiting_indexes = [
            index
            for index in range(fanout_state.item_count)
            if index not in collected_outputs
        ]
        if waiting_indexes:
            return DeferResult(consume_sequence=False)

        collect_state.released = True
        return PreparedInput(
            input_data=[
                collected_outputs[index]
                for index in range(fanout_state.item_count)
            ],
            scope_key=parent_scope,
        )

    @classmethod
    def get_output_schema(
        cls,
        config: dict | None = None,
        input_schema: WorkflowIOSchema | None = None,
        port_id: str = "default",
    ) -> WorkflowIOSchema:
        fields = []
        if input_schema is not None:
            fields = [
                _as_collected_item_field(field)
                for field in input_schema.fields
            ]
            if not fields:
                fields = [
                    WorkflowValueField(
                        path="0",
                        label=input_schema.label or "Collected item",
                        value_type=input_schema.value_type,
                    )
                ]

        return WorkflowIOSchema(
            value_type=WorkflowValueType.LIST,
            flow_kind=WorkflowIOFlowKind.NORMAL,
            label="Collected results",
            description="Outputs all iteration results once, ordered by item index.",
            fields=fields,
        )
