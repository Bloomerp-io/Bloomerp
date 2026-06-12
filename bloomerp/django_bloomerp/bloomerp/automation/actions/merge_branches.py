from dataclasses import dataclass, field

from django import forms

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.schema import (
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueType,
)


class MergeBranchesForm(forms.Form):
    pass


@dataclass
class WaitForOtherBranchResult:
    arrived_branch_ids: list[int] = field(default_factory=list)
    waiting_for_branch_ids: list[int] = field(default_factory=list)


class MergeBranchExecutor(BaseExecutor):
    config_form = MergeBranchesForm
    input_requirement = WorkflowInputRequirement(
        value_type=WorkflowValueType.ANY,
        label="Branch input",
        description="Waits for every upstream branch, then passes the merged branch data downstream.",
    )

    @classmethod
    def get_output_schema(cls, config=None, input_schema=None):
        if input_schema is not None:
            return input_schema

        return WorkflowIOSchema(
            value_type=WorkflowValueType.OBJECT,
            label="Merged branches",
            description="Outputs the values collected from all upstream branches.",
        )

    def execute(self, trigger_data):
        return trigger_data
