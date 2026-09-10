from channels.layers import get_channel_layer
from django.contrib.auth.models import AnonymousUser

from bloomerp.channels.workflows.events import workflow_run_group_name
from bloomerp.channels.workflows.workflow_run_consumer import WorkflowRunConsumer
from bloomerp.models import User
from bloomerp.models.automation import Workflow
from bloomerp.router import BloomerpRouteRegistry
from bloomerp.tests.base import BloomerpChannelTestCase


class WorkflowRunConsumerTests(BloomerpChannelTestCase):
    def setUp(self) -> None:
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
        self.registry = BloomerpRouteRegistry()
        self.registry.register(
            re_path=r"^ws/automation/workflow-run/(?P<workflow_id>\d+)/$",
            route_type="websocket",
        )(WorkflowRunConsumer)

    def communicator_for(self, user):
        communicator = self.websocket_communicator(
            self.registry,
            f"/ws/automation/workflow-run/{self.workflow.id}/",
        )
        communicator.scope["user"] = user
        return communicator

    async def test_authorized_user_receives_workflow_run_events(self):
        communicator = self.communicator_for(self.user)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            workflow_run_group_name(self.workflow.id),
            {
                "type": "workflow_run_event",
                "payload": {
                    "type": "workflow_run",
                    "event": "node.started",
                    "workflow_id": self.workflow.id,
                    "run_id": 10,
                    "node_id": 20,
                    "sequence": 0,
                    "status": "RUNNING",
                },
            },
        )

        payload = await communicator.receive_json_from()
        self.assertEqual(payload["event"], "node.started")
        self.assertEqual(payload["node_id"], 20)
        await communicator.disconnect()

    async def test_anonymous_user_is_rejected(self):
        communicator = self.communicator_for(AnonymousUser())
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4401)

    async def test_user_without_change_access_is_rejected(self):
        communicator = self.communicator_for(self.unauthorized_user)
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4403)
