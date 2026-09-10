from celery import shared_task
from django.utils import timezone


@shared_task
def run_scheduled_workflow(workflow_id):
    from bloomerp.automation.run import run_workflow_sync, serialize_workflow_run_result
    from bloomerp.models.automation.workflow import Workflow

    workflow = Workflow.objects.get(id=workflow_id, active=True)
    workflow_run = run_workflow_sync(
        workflow,
        {
            "event": "schedule",
            "scheduled_at": timezone.now().isoformat(),
        },
    )
    return serialize_workflow_run_result(workflow_run)


@shared_task
def run_workflow_async(
    workflow_id,
    trigger_data,
    start_node_id=None,
    workflow_run_id=None,
    client_request_id=None,
):
    from bloomerp.automation.run import (
        deserialize_workflow_value,
        run_workflow_sync,
        serialize_workflow_run_result,
    )
    from bloomerp.channels.workflows.events import send_workflow_run_event
    from bloomerp.models.automation.workflow import Workflow
    from bloomerp.models.automation.workflow_run import WorkflowRun, WorkflowRunStatus

    workflow_run = (
        WorkflowRun.objects.filter(pk=workflow_run_id).first()
        if workflow_run_id is not None
        else None
    )
    workflow = Workflow.objects.filter(id=workflow_id, active=True).first()
    if workflow is None:
        if workflow_run is not None:
            workflow_run.status = WorkflowRunStatus.CANCELLED
            workflow_run.finished_at = timezone.now()
            workflow_run.save(
                update_fields=["status", "finished_at", "datetime_updated"]
            )
            send_workflow_run_event(
                workflow_run,
                "run.cancelled",
                client_request_id=client_request_id,
            )
        return None

    try:
        deserialized_trigger_data = deserialize_workflow_value(trigger_data)
        start_node = (
            workflow.nodes.get(id=start_node_id)
            if start_node_id is not None
            else None
        )
        if workflow_run is not None and workflow_run.workflow_id != workflow.id:
            raise ValueError("Workflow run does not belong to the workflow.")
        workflow_run = run_workflow_sync(
            workflow,
            deserialized_trigger_data,
            start_node=start_node,
            workflow_run=workflow_run,
            client_request_id=client_request_id,
        )
        return serialize_workflow_run_result(workflow_run)
    except Exception:
        if workflow_run is not None:
            workflow_run.refresh_from_db(fields=["status", "finished_at"])
            if workflow_run.status != WorkflowRunStatus.FAILED:
                workflow_run.status = WorkflowRunStatus.FAILED
                workflow_run.finished_at = timezone.now()
                workflow_run.save(
                    update_fields=["status", "finished_at", "datetime_updated"]
                )
                send_workflow_run_event(
                    workflow_run,
                    "run.failed",
                    client_request_id=client_request_id,
                )
        raise


@shared_task
def resume_workflow_async(
    workflow_run_step_id,
    output_data=None,
    has_output_data=False,
):
    from bloomerp.automation.run import (
        deserialize_workflow_value,
        resume_workflow_sync,
        serialize_workflow_run_result,
    )
    from bloomerp.models.automation.workflow_run_step import WorkflowRunStep

    paused_step = WorkflowRunStep.objects.get(id=workflow_run_step_id)
    if has_output_data:
        workflow_run = resume_workflow_sync(
            paused_step,
            output_data=deserialize_workflow_value(output_data),
        )
    else:
        workflow_run = resume_workflow_sync(paused_step)
    return serialize_workflow_run_result(workflow_run)
