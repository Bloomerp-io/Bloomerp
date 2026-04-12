from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_run import WorkflowRun
from bloomerp.models.automation.workflow_node import WorkflowNode

def run_workflow(workflow: Workflow, trigger_data:dict) -> WorkflowRun:
    """
    Initiates a workflow run for the given workflow.

    Args:
        workflow (Workflow): The workflow to be executed.
    Returns:
        WorkflowRun: The initiated workflow run instance.
    """
    # Get the trigger node
    trigger = workflow.get_trigger()
    
    # Create a recursive function
    def _execute_recursive(node:WorkflowNode, input_data:dict) -> None:
        output_data = node.execute(input_data)
        output_nodes = node.get_output_nodes()
        if output_nodes:
            for output_node in output_nodes:
                _execute_recursive(output_node, output_data)
        
    _execute_recursive(trigger, trigger_data)    
        
        
        
    
        
        
    
        