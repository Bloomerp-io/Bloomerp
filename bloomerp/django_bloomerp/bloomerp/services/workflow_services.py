from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_run import WorkflowRun
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.automation.flows.for_each import ForEachResult
from bloomerp.automation.flows.if_condition import BranchStopped


def _summarize_output(output_data) -> dict:
    if isinstance(output_data, ForEachResult):
        return {
            "kind": "fanout",
            "item_count": len(output_data.items),
        }

    if isinstance(output_data, BranchStopped):
        return {
            "kind": "branch_stopped",
            "reason": output_data.reason,
        }

    if isinstance(output_data, list):
        return {
            "kind": "list",
            "item_count": len(output_data),
        }

    if isinstance(output_data, dict):
        return {
            "kind": "object",
            "keys": sorted(output_data.keys()),
        }

    return {
        "kind": type(output_data).__name__,
    }


def _trace_node(
    trace: list[dict],
    node: WorkflowNode,
    status: str,
    output_data=None,
    error: Exception | None = None,
) -> None:
    entry = {
        "node_id": node.id,
        "node_type": node.type,
        "node_sub_type": node.node_sub_type_id,
        "status": status,
    }
    if output_data is not None:
        entry["output"] = _summarize_output(output_data)
    if error is not None:
        entry["error"] = str(error)
    trace.append(entry)


def format_execution_trace(trace: list[dict]) -> str:
    parts = []
    for entry in trace:
        output = entry.get("output") or {}
        output_kind = output.get("kind")
        suffix = f" ({output_kind})" if output_kind else ""
        parts.append(
            f"{entry['node_sub_type']}: {entry['status']}{suffix}"
        )
    return "; ".join(parts)

def run_workflow(workflow: Workflow, trigger_data:dict) -> WorkflowRun:
    """
    Initiates a workflow run for the given workflow.

    Args:
        workflow (Workflow): The workflow to be executed.
    Returns:
        WorkflowRun: The initiated workflow run instance.
    """
    workflow_run = WorkflowRun.objects.create(workflow=workflow)
    execution_trace: list[dict] = []
    workflow_run.execution_trace = execution_trace

    trigger = workflow.get_trigger()

    # Create a recursive function
    def _execute_recursive(node:WorkflowNode, input_data:dict|list[dict]) -> None:
        try:
            output_data = node.execute(input_data)
        except Exception as error:
            _trace_node(execution_trace, node, "error", error=error)
            raise

        _trace_node(execution_trace, node, "success", output_data=output_data)
        if isinstance(output_data, BranchStopped):
            return

        output_nodes = node.get_output_nodes()
        if not output_nodes:
            return

        if isinstance(output_data, ForEachResult):
            for index, item in enumerate(output_data.items):
                item_input = {
                    "item": item,
                    "index": index,
                    "collection": output_data.collection,
                }
                for output_node in output_nodes:
                    _execute_recursive(output_node, item_input)
            return

        for output_node in output_nodes:
            _execute_recursive(output_node, output_data)
        
    _execute_recursive(trigger, trigger_data)
    return workflow_run
        
        
        
    
        
        
    
        
