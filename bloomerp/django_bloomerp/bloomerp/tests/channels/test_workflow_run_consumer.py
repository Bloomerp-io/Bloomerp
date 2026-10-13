"""Exercise workflow-run access and event isolation as socket conversations."""

from typing import Any

from bloomerp.channels.workflows.events import workflow_run_group_name
from bloomerp.channels.workflows.workflow_run_consumer import WorkflowRunConsumer
from bloomerp.models import User
from bloomerp.models.automation import Workflow
from bloomerp.router import BloomerpRouteRegistry
from bloomerp.tests.base import (
    BloomerpChannelTestCase,
    ChannelAction,
    ChannelContext,
    ChannelScenario,
    Connect,
    Disconnect,
    ExpectJson,
    ExpectNoMessage,
    PublishGroupEvent,
)


class WorkflowRunConsumerTests(BloomerpChannelTestCase):
    """Declare workflow stream acceptance, rejection, and subscription scenarios."""

    def setUp(self) -> None:
        """Create read-only workflow fixtures and register the real consumer."""
        super().setUp()
        self.user = User.objects.create_superuser(
            username="workflow-run-observer",
            password="password",
        )
        self.unauthorized_user = User.objects.create_user(
            username="workflow-run-outsider",
            password="password",
        )
        self.workflow = Workflow.objects.create(name="Observed workflow")
        self.other_workflow = Workflow.objects.create(name="Other workflow")
        self.registry = BloomerpRouteRegistry()
        self.registry.register(
            re_path=r"^ws/automation/workflow-run/(?P<workflow_id>\d+)/$",
            route_type="websocket",
        )(WorkflowRunConsumer)

    async def assert_subscription_removed(self, context: ChannelContext) -> None:
        """Verify disconnect removed the subscription from the in-memory backend."""
        self.assertNotIn(
            workflow_run_group_name(self.workflow.pk), context.layer.groups
        )

    def get_test_scenarios(self) -> list[ChannelScenario]:
        """Return conversations covering access gates, delivery, and cleanup."""
        path = f"/ws/automation/workflow-run/{self.workflow.pk}/"
        group = workflow_run_group_name(self.workflow.pk)
        payload: dict[str, Any] = {
            "type": "workflow_run",
            "event": "node.started",
            "workflow_id": self.workflow.pk,
            "run_id": 10,
            "node_id": 20,
            "sequence": 0,
            "status": "RUNNING",
        }
        event = {"type": "workflow_run_event", "payload": payload}
        return [
            ChannelScenario(
                name="authorized observer receives the complete event",
                steps=[
                    Connect(path=path, user=self.user),
                    PublishGroupEvent(group=group, event=event),
                    ExpectJson(payload=payload),
                    Disconnect(),
                    ChannelAction(
                        name="workflow subscription removed",
                        execute=self.assert_subscription_removed,
                    ),
                ],
            ),
            ChannelScenario(
                name="anonymous visitor is rejected",
                steps=[Connect(path=path, accepted=False, close_code=4401)],
            ),
            ChannelScenario(
                name="user without change access is rejected",
                steps=[
                    Connect(
                        path=path,
                        user=self.unauthorized_user,
                        accepted=False,
                        close_code=4403,
                    )
                ],
            ),
            ChannelScenario(
                name="workflow streams are isolated",
                steps=[
                    Connect(path=path, user=self.user),
                    Connect(
                        path=f"/ws/automation/workflow-run/{self.other_workflow.pk}/",
                        user=self.user,
                        socket="other",
                    ),
                    PublishGroupEvent(group=group, event=event),
                    ExpectJson(payload=payload),
                    ExpectNoMessage(socket="other"),
                ],
            ),
        ]
