import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from bloomerp.models.automation.workflow_run import WorkflowRun


logger = logging.getLogger(__name__)


def workflow_run_group_name(workflow_id: int) -> str:
    return f"workflow_{workflow_id}_runs"


def send_workflow_run_event(
    workflow_run: WorkflowRun,
    event: str,
    *,
    client_request_id: str | None = None,
    node_id: int | None = None,
    sequence: int | None = None,
    status: str | None = None,
) -> None:
    """Publish a compact workflow-run lifecycle event to observing builders."""
    payload = {
        "type": "workflow_run",
        "event": event,
        "workflow_id": workflow_run.workflow_id,
        "run_id": workflow_run.id,
        "status": status or workflow_run.status,
    }
    if client_request_id:
        payload["client_request_id"] = client_request_id
    if node_id is not None:
        payload["node_id"] = node_id
    if sequence is not None:
        payload["sequence"] = sequence

    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return

        async_to_sync(channel_layer.group_send)(
            workflow_run_group_name(workflow_run.workflow_id),
            {
                "type": "workflow_run_event",
                "payload": payload,
            },
        )
    except Exception:
        logger.warning(
            "Could not publish workflow run event %s for run %s.",
            event,
            workflow_run.id,
            exc_info=True,
        )
