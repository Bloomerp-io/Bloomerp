from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_run import WorkflowRun


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
    
    # Create a new workflow run
    
    