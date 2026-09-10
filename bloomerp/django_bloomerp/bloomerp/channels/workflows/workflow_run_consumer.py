from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from bloomerp.channels.workflows.events import workflow_run_group_name
from bloomerp.models.automation.workflow import Workflow
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router


@database_sync_to_async
def _can_observe_workflow(user, workflow_id: int) -> bool:
    workflow = Workflow.objects.filter(pk=workflow_id).first()
    return bool(
        workflow
        and UserPolicyManager(user).has_access_to_object(
            workflow,
            BloomerpPermission.CHANGE,
        )
    )


@router.register(
    re_path=r"^ws/automation/workflow-run/(?P<workflow_id>\d+)/$",
    route_type="websocket",
)
class WorkflowRunConsumer(AsyncJsonWebsocketConsumer):
    """Stream workflow-run events to authorized workflow builders."""

    group_name: str | None = None

    async def connect(self) -> None:
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return

        workflow_id = int(self.scope["url_route"]["kwargs"]["workflow_id"])
        if not await _can_observe_workflow(user, workflow_id):
            await self.close(code=4403)
            return

        self.group_name = workflow_run_group_name(workflow_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code: int) -> None:
        if self.group_name:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
            )

    async def workflow_run_event(self, event: dict) -> None:
        await self.send_json(event.get("payload", {}))
