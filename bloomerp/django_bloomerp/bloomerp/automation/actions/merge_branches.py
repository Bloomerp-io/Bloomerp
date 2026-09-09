from django import forms

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.results import DeferResult, PreparedInput
from bloomerp.automation.schema import (
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueType,
)


class MergeBranchesForm(forms.Form):
    pass


class MergeBranchExecutor(BaseExecutor):
    config_form = MergeBranchesForm
    input_requirement = WorkflowInputRequirement(
        value_type=WorkflowValueType.ANY,
        label="Branch input",
        description="Waits for every upstream branch, then passes the merged branch data downstream.",
    )

    @classmethod
    def get_output_schema(
        cls,
        config=None,
        input_schema=None,
        port_id="default",
    ):
        if input_schema is not None:
            return input_schema

        return WorkflowIOSchema(
            value_type=WorkflowValueType.OBJECT,
            label="Merged branches",
            description="Outputs the values collected from all upstream branches.",
        )

    def execute(self, trigger_data):
        return trigger_data

    def prepare(self, input_data, context):
        incoming_edges = list(
            context.node.incoming_edges.select_related("from_node").order_by("id")
        )
        required_node_ids = [edge.from_node_id for edge in incoming_edges]
        merge_state = context.state.get_merge_state(context.node.id, context.scope_key)
        if merge_state.released:
            return DeferResult()

        if context.from_node is not None:
            context.set_transient_output(
                "merge",
                context.scope_key,
                context.from_node.id,
                input_data,
            )
            if context.from_step is not None:
                merge_state.branch_output_step_ids[context.from_node.id] = context.from_step.id

        branch_outputs = {}
        for branch_node_id in required_node_ids:
            for ancestor_scope in context.scope_ancestors():
                found, output = context.get_transient_output(
                    "merge",
                    ancestor_scope,
                    branch_node_id,
                )
                if found:
                    branch_outputs[branch_node_id] = output
                    break

                ancestor_state = next(
                    (
                        item
                        for item in context.state.merge_states
                        if item.node_id == context.node.id
                        and item.scope_key == ancestor_scope
                    ),
                    None,
                )
                if ancestor_state and branch_node_id in ancestor_state.branch_output_step_ids:
                    output_step = context.workflow_run.steps.get(
                        pk=ancestor_state.branch_output_step_ids[branch_node_id]
                    )
                    branch_outputs[branch_node_id] = context.load_step_output(output_step)
                    break

        waiting_branch_ids = [
            node_id
            for node_id in required_node_ids
            if node_id not in branch_outputs
        ]
        if waiting_branch_ids:
            retry_scopes = ()
            if context.from_node is not None:
                retry_scopes = tuple(
                    item.scope_key
                    for item in context.state.merge_states
                    if item.node_id == context.node.id
                    and not item.released
                    and len(item.scope_key) > len(context.scope_key)
                    and item.scope_key[:len(context.scope_key)] == context.scope_key
                )
            return DeferResult(
                output={
                    "arrived_branch_ids": sorted(branch_outputs),
                    "waiting_for_branch_ids": waiting_branch_ids,
                },
                trace=True,
                persist_step=True,
                retry_scope_keys=retry_scopes,
            )

        merge_state.released = True
        return PreparedInput(
            input_data={
                f"node_{edge.from_node_id}": branch_outputs[edge.from_node_id]
                for edge in incoming_edges
            }
        )
