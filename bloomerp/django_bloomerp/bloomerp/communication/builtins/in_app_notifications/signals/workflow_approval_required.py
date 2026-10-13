
from bloomerp.models.automation.workflow_run_step import WorkflowRunStep
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from bloomerp.communication.inbox_sources import (
    InboxSourceDelivery,
    InboxSourceExecutionResult,
)

def resolve(*, instance:WorkflowRunStep, **kwargs):
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
        
    node = instance.node
    parameters = node.parameters or {}
    
    approver_groups = parameters.get("approver_groups", [])
    approver_users = parameters.get("approver_users", [])
    
    creator = node.workflow.created_by
    users = get_user_model().objects.filter(
        id__in=approver_users
    )
    groups = Group.objects.filter(id__in=approver_groups)
    
    group_users = get_user_model().objects.filter(groups__in=groups)
    
    total_users = set()
    total_users.add(creator)
    total_users.update(users)
    total_users.update(group_users)
    
    return InboxFolder.get_folders_by_users_and_type(
        users=list(total_users),
        folder_type=INBOX_FOLDER_REGISTRY.IN_APP_NOTIFICATIONS.key
    )
    
def predicate(*, instance:WorkflowRunStep, created: bool, raw: bool = False, **kwargs,) -> bool:
    return created and instance.action_id == "HUMAN_IN_THE_LOOP"

def handle(folders, *, instance, **kwargs):
    from bloomerp.communication.builtins.in_app_notifications.base import SystemMessage
    deliveries = []
    
    run = instance.workflow_run
    
    for folder in folders:
        item = SystemMessage.create_item(
            message_type="workflow",
            folder=folder,
            data={
                "workflow_run_id": run.id,
                "status": instance.status,
            },
        )
        
        deliveries.append(
            InboxSourceDelivery(
                folder=folder,
                items=(item, )
            )
        )
    
    return InboxSourceExecutionResult(
        deliveries=deliveries,
    )
