from celery import shared_task
from django.utils import timezone


@shared_task
def run_scheduled_workflow(workflow_id):
    from bloomerp.models.automation.workflow import Workflow
    from bloomerp.services.workflow_services import run_workflow_sync, serialize_workflow_run_result

    workflow = Workflow.objects.get(id=workflow_id, active=True)
    workflow_run = run_workflow_sync(
        workflow,
        {
            "event": "schedule",
            "scheduled_at": timezone.now().isoformat(),
        },
    )
    return serialize_workflow_run_result(workflow_run)
