from celery import shared_task
from django.utils import timezone

@shared_task
def run_scheduled_workflow(workflow_id):
    from bloomerp.models.automation.workflow import Workflow
    from bloomerp.automation.run import run_workflow_sync, serialize_workflow_run_result

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
def run_workflow_async(workflow_id, trigger_data, start_node_id=None):
    from bloomerp.models.automation.workflow import Workflow
    from bloomerp.automation.run import (
        deserialize_workflow_value,
        run_workflow_sync,
        serialize_workflow_run_result,
    )

    workflow = Workflow.objects.filter(id=workflow_id, active=True).first()
    if workflow is None:
        return None

    deserialized_trigger_data = deserialize_workflow_value(trigger_data)
    start_node = (
        workflow.nodes.get(id=start_node_id)
        if start_node_id is not None
        else None
    )
    workflow_run = run_workflow_sync(
        workflow,
        deserialized_trigger_data,
        start_node=start_node,
    )
    return serialize_workflow_run_result(workflow_run)


@shared_task
def resume_workflow_async(
    workflow_run_step_id,
    output_data=None,
    has_output_data=False,
):
    from bloomerp.models.automation.workflow_run_step import WorkflowRunStep
    from bloomerp.automation.run import (
        deserialize_workflow_value,
        resume_workflow_sync,
        serialize_workflow_run_result,
    )

    paused_step = WorkflowRunStep.objects.get(id=workflow_run_step_id)
    if has_output_data:
        workflow_run = resume_workflow_sync(
            paused_step,
            output_data=deserialize_workflow_value(output_data),
        )
    else:
        workflow_run = resume_workflow_sync(paused_step)
    return serialize_workflow_run_result(workflow_run)
