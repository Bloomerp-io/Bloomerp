from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet

from bloomerp.communication.inbox_sources import (
    InboxSourceDelivery,
    InboxSourceExecutionResult,
)
from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
from bloomerp.models.automation.workflow_run_step import (
    WorkflowRunStep,
    WorkflowRunStepStatus,
)
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder


def resolve(*, instance: WorkflowRunStep, **kwargs: Any) -> QuerySet[InboxFolder]:
    """Deliver approval requests to configured approvers and the workflow creator."""
    parameters = instance.node.parameters or {}
    users = get_user_model().objects.filter(
        Q(pk__in=parameters.get("approver_users", []))
        | Q(groups__in=parameters.get("approver_groups", []))
        | Q(pk=instance.node.workflow.created_by_id)
    ).distinct()
    return InboxFolder.get_folders_by_users_and_type(
        users=list(users),
        folder_type=INBOX_FOLDER_REGISTRY.IN_APP_NOTIFICATIONS.key,
    )


def predicate(
    *,
    instance: WorkflowRunStep,
    created: bool,
    raw: bool = False,
    **kwargs: Any,
) -> bool:
    """Notify only when a human review step is first paused."""
    return (
        created
        and not raw
        and instance.action_id == "HUMAN_IN_THE_LOOP"
        and instance.status == WorkflowRunStepStatus.PAUSED
        and instance.node_id is not None
    )


def handle(
    folders: QuerySet[InboxFolder],
    *,
    instance: WorkflowRunStep,
    **kwargs: Any,
) -> InboxSourceExecutionResult:
    """Save the review message and exact paused step with each notification."""
    from bloomerp.communication.builtins.in_app_notifications.base import SystemMessage

    deliveries = []
    for folder in folders:
        item = SystemMessage.create_item(
            message_type="workflow",
            folder=folder,
            data={
                "workflow_run_id": instance.workflow_run_id,
                "status": instance.status,
                "approval_step_id": instance.pk,
                "approval_message": (instance.node.parameters or {}).get("message", ""),
            },
        )
        deliveries.append(InboxSourceDelivery(folder=folder, items=(item,)))

    return InboxSourceExecutionResult(deliveries=tuple(deliveries))
