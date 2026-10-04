"""Verify socket steps and resource isolation in the reusable channel runner."""

from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from bloomerp.router import BloomerpRouteRegistry
from bloomerp.tests.base.channel_test_case import (
    BloomerpChannelTestCase,
    ChannelAction,
    ChannelContext,
    ChannelScenario,
    Connect,
    ExpectClose,
    ExpectJson,
    SendJson,
)


class ScenarioConsumer(AsyncJsonWebsocketConsumer):
    """Provide a small real transport for testing the scenario runner."""

    async def connect(self) -> None:
        """Subscribe to a test group before accepting the connection."""
        await self.channel_layer.group_add("scenario-test", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code: int) -> None:
        """Release the test subscription when the client disconnects."""
        await self.channel_layer.group_discard("scenario-test", self.channel_name)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        """Echo JSON values or close when explicitly requested."""
        if content == {"close": True}:
            await self.close(code=4400)
        else:
            await self.send_json(content)


def has_message(payload: Any) -> bool:
    """Check that an echo contains the expected message."""
    return isinstance(payload, dict) and payload.get("message") == "hello"


class ChannelTestCaseTests(BloomerpChannelTestCase):
    """Exercise real sockets and failure paths of the shared runner."""

    def setUp(self) -> None:
        """Register the test transport and initialize hook observations."""
        super().setUp()
        self.registry = BloomerpRouteRegistry()
        self.registry.register(path="ws/scenario/", route_type="websocket")(
            ScenarioConsumer
        )
        self.contexts: list[ChannelContext] = []
        self.hooks: list[str] = []

    def prepare_scenario(self) -> None:
        """Record execution of a synchronous preparation hook."""
        self.hooks.append("prepare")

    def cleanup_scenario(self) -> None:
        """Record execution of a synchronous cleanup hook."""
        self.hooks.append("cleanup")

    async def capture_context(self, context: ChannelContext) -> None:
        """Keep the scenario context so resource release can be inspected."""
        self.contexts.append(context)

    async def fail_action(self, context: ChannelContext) -> None:
        """Fail after recording live sockets to exercise unconditional cleanup."""
        self.contexts.append(context)
        raise AssertionError("intentional failure")

    def get_test_scenarios(self) -> list[ChannelScenario]:
        """Declare JSON echo and server-close conversations."""
        return [
            ChannelScenario(
                name="JSON echo",
                steps=[
                    Connect(path="/ws/scenario/"),
                    SendJson(payload={"message": "hello"}),
                    ExpectJson(payload={"message": "hello"}, validators=[has_message]),
                    SendJson(payload=None),
                    ExpectJson(payload=None),
                ],
            ),
            ChannelScenario(
                name="server closes socket",
                steps=[
                    Connect(path="/ws/scenario/"),
                    SendJson(payload={"close": True}),
                    ExpectClose(code=4400),
                ],
            ),
        ]

    async def test_failure_releases_all_sockets_and_runs_cleanup(self) -> None:
        """A failed action reports its step and releases both live connections."""
        scenario = ChannelScenario(
            name="failure cleanup",
            prepare=self.prepare_scenario,
            cleanup=self.cleanup_scenario,
            steps=[
                Connect(path="/ws/scenario/"),
                Connect(path="/ws/scenario/", socket="second"),
                ChannelAction(name="deliberate failure", execute=self.fail_action),
            ],
        )
        with self.assertRaisesRegex(AssertionError, "step 3 .*deliberate failure"):
            await self._run_channel_scenario(scenario)
        self.assertEqual(self.hooks, ["prepare", "cleanup"])
        context = self.contexts[0]
        self.assertEqual(context.layer.groups, {})
        self.assertTrue(
            all(socket.future.done() for socket in context.sockets.values())
        )

    async def test_scenarios_use_distinct_layers(self) -> None:
        """Every conversation receives a fresh backend without prior subscriptions."""
        scenario = ChannelScenario(
            name="fresh layer",
            steps=[
                Connect(path="/ws/scenario/"),
                ChannelAction(name="capture", execute=self.capture_context),
            ],
        )
        await self._run_channel_scenario(scenario)
        await self._run_channel_scenario(scenario)
        self.assertIsNot(self.contexts[0].layer, self.contexts[1].layer)
        self.assertEqual(self.contexts[0].layer.groups, {})
        self.assertEqual(self.contexts[1].layer.groups, {})
