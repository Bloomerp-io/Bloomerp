from dataclasses import dataclass
import json
from typing import Any, Literal

from django.core.files.base import ContentFile
from django.db import DatabaseError, transaction
from django.db.models import Max
from django.utils import timezone

from bloomerp.automation.results import (
    DeferResult,
    FanOutResult,
    PauseResult,
    RouteResult,
    StopBranchResult,
)
from bloomerp.automation.runtime import WorkflowNodeExecutionContext
from bloomerp.automation.serialization import (
    OUTPUT_UNSET,
    deserialize_workflow_value,
    serialize_workflow_value,
)
from bloomerp.automation.workflow_state import ScopeKey, WorkflowRunState
from bloomerp.celery.tasks.workflow_task import resume_workflow_async, run_workflow_async
from bloomerp.communication.inbox_sources import publish_event
from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.models.automation.workflow_run import WorkflowRun
from bloomerp.models.automation.workflow_run_step import (
    WorkflowRunStep,
    WorkflowRunStepStatus,
)
from bloomerp.utils.json_serialization import make_json_safe

_NO_OUTPUT = OUTPUT_UNSET
_IN_FAILED_SQL_TRANSACTION = "25P02"


class _WorkflowPaused(Exception):
    pass


@dataclass(frozen=True)
class WorkflowExecutionFrame:
    node: WorkflowNode
    input_data: object
    from_node: WorkflowNode | None = None
    from_step: WorkflowRunStep | None = None
    scope_key: ScopeKey = ()



def _execute_node(node: WorkflowNode, input_data: object) -> object:
    """Execute a node without allowing a handled database error to break its caller."""
    if not transaction.get_connection().in_atomic_block:
        return node.execute(input_data)

    output_data = _NO_OUTPUT
    try:
        with transaction.atomic():
            output_data = node.execute(input_data)
    except DatabaseError as error:
        is_handled_error = (
            isinstance(output_data, dict)
            and output_data.get("status") == "error"
        )
        if not is_handled_error or not _is_in_failed_sql_transaction(error):
            raise

    return output_data


def _summarize_output(output_data) -> dict:
    if isinstance(output_data, FanOutResult):
        return {
            "kind": "fanout",
            "item_count": len(output_data.items),
        }

    if isinstance(output_data, StopBranchResult):
        return {
            "kind": "branch_stopped",
            "reason": output_data.reason,
        }

    if isinstance(output_data, DeferResult):
        if (
            isinstance(output_data.output, dict)
            and "waiting_for_branch_ids" in output_data.output
        ):
            return {
                "kind": "waiting_for_branches",
                **serialize_workflow_value(output_data.output),
            }
        return {
            "kind": "deferred",
            "details": serialize_workflow_value(output_data.output),
        }

    if isinstance(output_data, RouteResult):
        return {
            "kind": "route",
            "port_id": output_data.port_id,
            "output": _summarize_output(output_data.output),
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
        "output": None,
    }
    if output_data is not None:
        if isinstance(output_data, RouteResult):
            entry["output"] = make_json_safe(output_data.output)
            entry["output_summary"] = _summarize_output(output_data.output)
            entry["route"] = {"port_id": output_data.port_id}
        elif isinstance(
            output_data,
            (
                FanOutResult,
                StopBranchResult,
                DeferResult,
            ),
        ):
            entry["output"] = _summarize_output(output_data)
        else:
            entry["output"] = make_json_safe(output_data)
            entry["output_summary"] = _summarize_output(output_data)
    if error is not None:
        entry["error"] = str(error)
    trace.append(entry)


def load_step_output(step: WorkflowRunStep) -> dict | Any:
    """Loads the output of a step into python

    Args:
        step (WorkflowRunStep): the workflow run step

    Raises:
        ValueError: raises when workflow does not contain step output

    Returns:
        dict | Any: the step output
    """
    if not step.output_file:
        raise ValueError("Workflow run step does not contain a stored output.")

    with step.output_file.open("rb") as output_file:
        return deserialize_workflow_value(
            json.loads(output_file.read().decode("utf-8"))
        )


def _execute_workflow_state(
    workflow: Workflow,
    workflow_run: WorkflowRun,
    state: WorkflowRunState,
    start_frames: list[WorkflowExecutionFrame],
    related_object=None,
) -> WorkflowRun:
    execution_trace: list[dict] = []
    transient_outputs = {}
    workflow_run.execution_trace = execution_trace

    def _execute_recursive(
        node: WorkflowNode,
        input_data,
        from_node: WorkflowNode | None = None,
        from_step: WorkflowRunStep | None = None,
        scope_key: ScopeKey = (),
    ) -> None:
        current_sequence = state.next_sequence
        state.next_sequence += 1
        state.current_node_id = node.id
        state.current_step_id = None
        state.from_node_id = from_node.id if from_node is not None else None
        state.scope_key = scope_key

        executor = node.get_executor()
        try:
            prepared = executor.prepare(
                input_data,
                WorkflowNodeExecutionContext(
                    node=node,
                    workflow_run=workflow_run,
                    state=state,
                    from_node=from_node,
                    from_step=from_step,
                    scope_key=scope_key,
                    transient_outputs=transient_outputs,
                    load_step_output=load_step_output,
                ),
            )
            if isinstance(prepared, DeferResult):
                if not prepared.consume_sequence:
                    state.next_sequence -= 1
                if prepared.trace:
                    _trace_node(
                        execution_trace,
                        node,
                        "deferred",
                        output_data=prepared,
                    )
                workflow_run.create_step(
                    node=node,
                    sequence=current_sequence,
                    status=WorkflowRunStepStatus.COMPLETED,
                    state=state,
                    enabled=workflow.enable_logging and prepared.persist_step,
                    output_data=prepared,
                )
                for retry_scope_key in prepared.retry_scope_keys:
                    _execute_recursive(
                        node=node,
                        input_data={},
                        scope_key=retry_scope_key,
                    )
                return

            input_data = prepared.input_data
            if prepared.scope_key is not None:
                scope_key = prepared.scope_key
                state.scope_key = scope_key
            output_data = _execute_node(node, input_data)
        except Exception as error:
            _trace_node(execution_trace, node, "error", error=error)
            workflow_run.create_step(
                node=node,
                sequence=current_sequence,
                status=WorkflowRunStepStatus.FAILED,
                state=state,
                enabled=workflow.enable_logging,
            )
            raise

        is_paused = isinstance(output_data, PauseResult)
        persisted_output = output_data.output if is_paused else output_data
        if isinstance(output_data, RouteResult):
            persisted_output = output_data.output
        if isinstance(output_data, FanOutResult):
            state.set_fanout_state(
                node.id,
                scope_key,
                len(output_data.items),
            )

        _trace_node(
            execution_trace,
            node,
            "paused" if is_paused else "success",
            output_data=output_data.output if is_paused else output_data,
        )
        current_step = workflow_run.create_step(
            node=node,
            sequence=current_sequence,
            status=(
                WorkflowRunStepStatus.PAUSED
                if is_paused
                else WorkflowRunStepStatus.COMPLETED
            ),
            state=state,
            enabled=workflow.enable_logging or is_paused,
            output_data=persisted_output,
        )
        if is_paused:
            raise _WorkflowPaused

        if isinstance(output_data, StopBranchResult):
            return

        if isinstance(output_data, RouteResult):
            port_id = output_data.port_id
            routed_output = output_data.output
        elif isinstance(output_data, FanOutResult):
            port_id = output_data.port_id
            routed_output = output_data
        else:
            port_id = "default"
            routed_output = output_data

        available_port_ids = {port.id for port in node.get_output_ports()}
        if port_id not in available_port_ids:
            raise ValueError(
                f"Node {node.node_sub_type_id!r} returned unknown output port {port_id!r}."
            )

        output_edges = list(
            node.outgoing_edges.filter(output_port=port_id)
            .select_related("to_node")
            .order_by("id")
        )
        if not output_edges:
            return

        if isinstance(routed_output, FanOutResult):
            for index, item in enumerate(routed_output.items):
                item_input = {
                    "item": item,
                    "index": index,
                }
                for edge in output_edges:
                    _execute_recursive(
                        node=edge.to_node,
                        input_data=item_input,
                        from_node=node,
                        from_step=current_step,
                        scope_key=scope_key + ((node.id, index),),
                    )
            return

        for edge in output_edges:
            _execute_recursive(
                node=edge.to_node,
                input_data=routed_output,
                from_node=node,
                from_step=current_step,
                scope_key=scope_key,
            )

    try:
        for frame in start_frames:
            _execute_recursive(
                node=frame.node,
                input_data=frame.input_data,
                from_node=frame.from_node,
                from_step=frame.from_step,
                scope_key=frame.scope_key,
            )
    except _WorkflowPaused:
        return workflow_run
    except Exception:
        publish_event(
            "workflow.result",
            workflow_run_id=str(workflow_run.id),
            status="failed",
            execution_trace=execution_trace,
            related_object=related_object,
            completed_at=timezone.now(),
        )
        raise

    publish_event(
        "workflow.result",
        workflow_run_id=str(workflow_run.id),
        status="successful",
        execution_trace=execution_trace,
        related_object=related_object,
        completed_at=timezone.now(),
    )

    return workflow_run


def _get_active_workflow(workflow: Workflow) -> Workflow | None:
    """Return the current database state only when the workflow is active."""
    return Workflow.objects.filter(pk=workflow.pk, active=True).first()


def run_workflow_sync(
    workflow: Workflow,
    trigger_data: dict,
    start_node: WorkflowNode | None = None,
) -> WorkflowRun | None:
    if start_node is not None and start_node.workflow_id != workflow.id:
        raise ValueError("Start node does not belong to the workflow.")

    workflow = _get_active_workflow(workflow)
    if workflow is None:
        return None

    workflow_run = WorkflowRun.objects.create(workflow=workflow)
    state = WorkflowRunState(
        workflow_id=workflow.id,
        workflow_run_id=workflow_run.id,
    )
    node = start_node or workflow.get_trigger()
    if node is None:
        raise ValueError("Workflow does not have a node to execute.")

    related_object = (
        trigger_data.get("instance")
        if isinstance(trigger_data, dict)
        else None
    )
    return _execute_workflow_state(
        workflow=workflow,
        workflow_run=workflow_run,
        state=state,
        start_frames=[WorkflowExecutionFrame(node=node, input_data=trigger_data)],
        related_object=related_object,
    )


def _load_run_state(step: WorkflowRunStep) -> WorkflowRunState:
    if not step.state:
        raise ValueError("Workflow run step does not contain a resumable state.")

    return WorkflowRunState.model_validate(step.state)


def _is_in_failed_sql_transaction(error: DatabaseError) -> bool:
    database_error = error.__cause__
    return (
        getattr(database_error, "sqlstate", None) == _IN_FAILED_SQL_TRANSACTION
        or getattr(database_error, "pgcode", None) == _IN_FAILED_SQL_TRANSACTION
    )

def _replace_step_output(step: WorkflowRunStep, output_data) -> None:
    serialized_output = serialize_workflow_value(output_data)
    step.output_file.save(
        f"workflow-run-{step.workflow_run_id}-step-{step.sequence}.json",
        ContentFile(json.dumps(serialized_output).encode("utf-8")),
        save=False,
    )


def resume_workflow_sync(
    paused_step: WorkflowRunStep,
    output_data=_NO_OUTPUT,
) -> WorkflowRun:
    """Resume an existing workflow run after a paused step."""
    with transaction.atomic():
        paused_step = WorkflowRunStep.objects.select_for_update().select_related(
            "workflow_run__workflow"
        ).get(pk=paused_step.pk)
        if paused_step.status != WorkflowRunStepStatus.PAUSED:
            raise ValueError("Only paused workflow steps can be resumed.")

        workflow_run = WorkflowRun.objects.select_for_update().get(
            pk=paused_step.workflow_run_id
        )
        workflow = paused_step.workflow_run.workflow
        state = _load_run_state(paused_step)
        if state.workflow_id != workflow.id or state.workflow_run_id != workflow_run.id:
            raise ValueError("Workflow state does not match the paused workflow run.")

        latest_sequence = workflow_run.steps.aggregate(value=Max("sequence"))["value"]
        next_persisted_sequence = 0 if latest_sequence is None else latest_sequence + 1
        state.next_sequence = max(state.next_sequence, next_persisted_sequence)

        paused_node = workflow.nodes.filter(pk=state.current_node_id).first()
        if paused_node is None:
            raise ValueError("Paused workflow node no longer exists.")

        if output_data is _NO_OUTPUT:
            output_data = load_step_output(paused_step)
        else:
            _replace_step_output(paused_step, output_data)

        paused_step.status = WorkflowRunStepStatus.COMPLETED
        paused_step.save(
            update_fields=["status", "output_file", "datetime_updated"]
        )

        start_frames = [
            WorkflowExecutionFrame(
                node=output_node,
                input_data=output_data,
                from_node=paused_node,
                from_step=paused_step,
                scope_key=state.scope_key,
            )
            for output_node in paused_node.get_output_nodes()
        ]
        return _execute_workflow_state(
            workflow=workflow,
            workflow_run=workflow_run,
            state=state,
            start_frames=start_frames,
        )



def resume_workflow(
    paused_step: WorkflowRunStep,
    output_data=_NO_OUTPUT,
) -> WorkflowRun | None:
    """Resume immediately or dispatch through Celery based on the workflow."""
    paused_step = WorkflowRunStep.objects.select_related(
        "workflow_run__workflow"
    ).get(pk=paused_step.pk)
    if paused_step.status != WorkflowRunStepStatus.PAUSED:
        raise ValueError("Only paused workflow steps can be resumed.")

    if not paused_step.workflow_run.workflow.run_asynchronously:
        return resume_workflow_sync(paused_step, output_data=output_data)

    if output_data is _NO_OUTPUT:
        resume_workflow_async.delay(paused_step.pk)
    else:
        resume_workflow_async.delay(
            paused_step.pk,
            serialize_workflow_value(output_data),
            True,
        )
    return None


def run_workflow(
    workflow: Workflow,
    trigger_data: dict,
    *,
    start_node: WorkflowNode | None = None,
    force:Literal["SYNC", "ASYNC"] | None = None
) -> WorkflowRun | None:
    """
    Initiates a workflow run for the given workflow.

    Args:
        workflow (Workflow): The workflow to be executed.
        start_node (WorkflowNode | None): Optional node to start from for debugging.
    """
    if start_node is not None and start_node.workflow_id != workflow.id:
        raise ValueError("Start node does not belong to the workflow.")

    workflow = _get_active_workflow(workflow)
    if workflow is None:
        return None

    if force not in {None, "SYNC", "ASYNC"}:
        raise ValueError("force must be 'SYNC', 'ASYNC', or None.")

    run_asynchronously = (
        force == "ASYNC"
        or (force is None and workflow.run_asynchronously)
    )
    if run_asynchronously:
        serialized_trigger_data = serialize_workflow_value(trigger_data)
        if start_node is None:
            run_workflow_async.delay(workflow.id, serialized_trigger_data)
        else:
            run_workflow_async.delay(
                workflow.id,
                serialized_trigger_data,
                start_node.id,
            )
        return None

    return run_workflow_sync(workflow, trigger_data, start_node=start_node)


def serialize_workflow_run_result(workflow_run: WorkflowRun | None) -> dict | None:
    if workflow_run is None:
        return None

    return {
        "workflow_run_id": str(workflow_run.id),
    }

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
