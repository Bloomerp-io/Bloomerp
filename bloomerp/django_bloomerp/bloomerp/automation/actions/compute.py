from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.schema import WorkflowIOSchema, WorkflowValueType
from bloomerp.forms.base_workflow_node_form import BaseWorkflowNodeForm
from django import forms

from bloomerp.widgets.code_editor_widget import CodeEditorWidget

class ComputeConfigForm(BaseWorkflowNodeForm):
    expression = forms.CharField(
        label="Expression",
        help_text="Enter a Python expression to compute. You can use fields from the model instance as variables in the expression.",
        widget=CodeEditorWidget(
            language="python",
        )
    )


class ComputeExecutor(BaseExecutor):
    """
    Evaluates a Python expression and stores the result in a specified field.
    """
    output_schema = WorkflowIOSchema(
        value_type=WorkflowValueType.ANY,
        label="Computed Value",
        description="The result of the evaluated expression.",
    )
    
    def execute(self, trigger_data):
        # Get the expression and target field from the action configuration
        expression = self.resolve_config(trigger_data).get("expression")
        
        if not expression:
            raise ValueError("The 'expression' must be defined in the action configuration.")

        # Evaluate the expression in the given context
        try:
            result = eval(expression)
        except Exception as e:
            return {
                "status": "error",
                "error_message": str(e),
            }

        # Store the result in the target field of the model instance
        return {
            "result": result,
            "status": "success",
        }