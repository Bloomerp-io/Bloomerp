from bloomerp.automation.base_executor import BaseExecutor, NodeExecutionError
from bloomerp.automation.results import PreparedInput
from bloomerp.automation.schema import (
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueType,
)
from bloomerp.forms.base_workflow_node_form import BaseWorkflowNodeForm
from django import forms
from bloomerp.models.automation.workflow import Workflow
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


class RunWorkflowForm(BaseWorkflowNodeForm):
    workflow_id = forms.IntegerField(
        widget=ForeignFieldWidget(
            model=Workflow,
            attrs={
                "class": "input w-full",
            },
        )
    )
    execution = forms.ChoiceField(
        initial="USE_WORKFLOW",
        choices=[
            ("USE_WORKFLOW", "Use workflow's execution setting"),
            ("ASYNC", "Run asynchronously"),
            ("SYNC", "Run synchronously"),
        ],
        widget=forms.Select(attrs={"class": "input w-full"}),
    )


class RunWorkflowExecutor(BaseExecutor):
    """Invoke another workflow and pass the current input through unchanged."""

    config_form = RunWorkflowForm

    @classmethod
    def _called_workflow_ids(cls, workflow: Workflow) -> set[int]:
        called_workflow_ids = set()
        for node in workflow.nodes.all():
            definition = node.node_sub_type
            if definition is None or definition.executor_cls is not cls:
                continue
            workflow_id = (node.parameters or {}).get("workflow_id")
            try:
                called_workflow_ids.add(int(workflow_id))
            except (TypeError, ValueError):
                continue
        return called_workflow_ids

    @classmethod
    def _would_create_cycle(cls, source_workflow_id: int, target_workflow_id: int) -> bool:
        pending = [target_workflow_id]
        visited = set()
        while pending:
            workflow_id = pending.pop()
            if workflow_id == source_workflow_id:
                return True
            if workflow_id in visited:
                continue
            visited.add(workflow_id)
            workflow = Workflow.objects.filter(pk=workflow_id).first()
            if workflow is not None:
                pending.extend(cls._called_workflow_ids(workflow) - visited)
        return False

    def prepare(self, input_data, context):
        config = self.resolve_config(
            input_data if isinstance(input_data, dict) else {"input": input_data}
        )
        workflow_id = config.get("workflow_id")
        try:
            target_workflow_id = int(workflow_id)
        except (TypeError, ValueError) as error:
            raise NodeExecutionError("Select a workflow to run.") from error

        if not Workflow.objects.filter(pk=target_workflow_id).exists():
            raise NodeExecutionError("The selected workflow does not exist.")
        if self._would_create_cycle(context.node.workflow_id, target_workflow_id):
            raise NodeExecutionError("Run Workflow calls may not create a cycle.")
        return PreparedInput(input_data=input_data)

    def execute(self, trigger_data):
        from bloomerp.automation.run import run_workflow

        config = self.resolve_config(trigger_data)
        workflow = Workflow.objects.get(id=config.get("workflow_id"))
        execution = config.get("execution", "USE_WORKFLOW")
        force = execution if execution in {"SYNC", "ASYNC"} else None
        run_workflow(workflow, trigger_data, force=force)
        return trigger_data

    @classmethod
    def get_output_schema(cls, config=None, input_schema=None, port_id="default"):
        return input_schema or WorkflowIOSchema(value_type=WorkflowValueType.ANY)
    
    @classmethod
    def get_input_requirement(cls, config=None):
        return WorkflowInputRequirement(
            label="A JSON Style object",
            value_type=WorkflowValueType.OBJECT,
            required=True,
        )
