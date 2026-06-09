from celery import shared_task
from django.apps import apps
from django.db.models import Model

from bloomerp.automation.flows.for_each import ForEachResult
from bloomerp.automation.flows.if_condition import BranchStopped
from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.models.automation.workflow_run import WorkflowRun
from bloomerp.models.automation.workflow_run_step import WorkflowRunStep, WorkflowRunStepStatus
from bloomerp.utils.json_serialization import make_json_safe


def _serialize_trigger_data(value):
    if isinstance(value, Model):
        return {
            "__model__": value._meta.label_lower,
            "pk": value.pk,
        }

    if isinstance(value, type) and issubclass(value, Model):
        return {
            "__model_class__": value._meta.label_lower,
        }

    if isinstance(value, dict):
        return {
            str(key): _serialize_trigger_data(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [_serialize_trigger_data(item) for item in value]

    return make_json_safe(value)

def _deserialize_trigger_data(value):
    if isinstance(value, dict):
        model_label = value.get("__model__")
        if model_label:
            model = apps.get_model(model_label)
            if model is None:
                return None
            return model.objects.filter(pk=value.get("pk")).first()

        model_class_label = value.get("__model_class__")
        if model_class_label:
            return apps.get_model(model_class_label)

        return {
            key: _deserialize_trigger_data(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [_deserialize_trigger_data(item) for item in value]

    return value

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
        if isinstance(output_data, (ForEachResult, BranchStopped)):
            entry["output"] = _summarize_output(output_data)
        else:
            entry["output"] = make_json_safe(output_data)
            entry["output_summary"] = _summarize_output(output_data)
    if error is not None:
        entry["error"] = str(error)
    trace.append(entry)


def _create_run_step(
    workflow_run: WorkflowRun,
    node: WorkflowNode,
    sequence: int,
    status: WorkflowRunStepStatus,
    enable_logging: bool,
) -> None:
    if not enable_logging:
        return

    WorkflowRunStep.objects.create(
        workflow_run=workflow_run,
        sequence=sequence,
        action_id=node.node_sub_type_id or str(node.id),
        status=status,
    )


def format_execution_trace(trace: list[dict]) -> str:
    parts = []
    for entry in trace:
        output = entry.get("output_summary") or {}
        output_kind = output.get("kind")
        suffix = f" ({output_kind})" if output_kind else ""
        parts.append(
            f"{entry['node_sub_type']}: {entry['status']}{suffix}"
        )
    return "; ".join(parts)

def run_workflow(workflow: Workflow, trigger_data:dict) -> WorkflowRun | None:
    """
    Initiates a workflow run for the given workflow.

    Args:
        workflow (Workflow): The workflow to be executed.
    """
    if workflow.run_asynchronously:
        serialized_trigger_data = _serialize_trigger_data(trigger_data)
        run_workflow_async.delay(workflow.id, serialized_trigger_data)
        return None

    return run_workflow_sync(workflow, trigger_data)


def run_workflow_sync(workflow: Workflow, trigger_data:dict) -> WorkflowRun:
    workflow_run = WorkflowRun.objects.create(workflow=workflow)
    execution_trace: list[dict] = []
    workflow_run.execution_trace = execution_trace

    trigger = workflow.get_trigger()
    sequence = 0

    # Create a recursive function
    def _execute_recursive(
        node:WorkflowNode, 
        input_data:dict|list[dict],
        workflow_run:WorkflowRun=workflow_run,
        enable_logging:bool = workflow.enable_logging,
        ) -> None:
        nonlocal sequence
        current_sequence = sequence
        sequence += 1

        try:
            output_data = node.execute(input_data)
        except Exception as error:
            _trace_node(execution_trace, node, "error", error=error)
            _create_run_step(
                workflow_run=workflow_run,
                node=node,
                sequence=current_sequence,
                status=WorkflowRunStepStatus.FAILED,
                enable_logging=enable_logging,
            )
            raise

        _trace_node(execution_trace, node, "success", output_data=output_data)
        _create_run_step(
            workflow_run=workflow_run,
            node=node,
            sequence=current_sequence,
            status=WorkflowRunStepStatus.COMPLETED,
            enable_logging=enable_logging,
        )
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
                    _execute_recursive(
                        node=output_node, 
                        input_data=item_input, 
                        workflow_run=workflow_run, 
                        enable_logging=enable_logging,
                    )
            return

        for output_node in output_nodes:
            _execute_recursive(
                node=output_node, 
                input_data=output_data, 
                workflow_run=workflow_run, 
                enable_logging=enable_logging,
            )
    
    # Run the actual workflow
    _execute_recursive(
        node=trigger, 
        input_data=trigger_data, 
        workflow_run=workflow_run,
        enable_logging=workflow.enable_logging,
    )
    
    return workflow_run


@shared_task
def run_workflow_async(workflow_id, trigger_data):
    workflow = Workflow.objects.get(id=workflow_id)
    deserialized_trigger_data = _deserialize_trigger_data(trigger_data)
    return run_workflow_sync(workflow, deserialized_trigger_data)
