"""Run ordered WebSocket conversations through Bloomerp's route registry."""

import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from channels.db import database_sync_to_async
from channels.layers import InMemoryChannelLayer, get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import AnonymousUser
from django.test import TransactionTestCase, override_settings

from bloomerp.router import BloomerpRouteRegistry


@dataclass(kw_only=True)
class Connect:
    """Open a named socket and assert acceptance or a rejection close code."""

    path: str
    user: AbstractBaseUser | AnonymousUser | None = None
    socket: str = "default"
    headers: list[tuple[bytes, bytes]] = field(default_factory=list)
    accepted: bool = True
    close_code: int | None = None
    subprotocol: str | None = None
    timeout: float = 1.0


@dataclass(kw_only=True)
class SendJson:
    """Send a JSON value from a named client socket."""

    payload: Any
    socket: str = "default"


@dataclass(kw_only=True)
class PublishGroupEvent:
    """Publish a real channel-layer event to a consumer group."""

    group: str
    event: dict[str, Any]


EXPECTED_JSON_UNSET = object()


@dataclass(kw_only=True)
class ExpectJson:
    """Receive JSON and compare it exactly or apply named message validators."""

    payload: Any = EXPECTED_JSON_UNSET
    validators: list[Callable[[Any], bool]] = field(default_factory=list)
    socket: str = "default"
    timeout: float = 1.0


@dataclass(kw_only=True)
class ExpectNoMessage:
    """Assert that a named socket emits nothing within a bounded interval."""

    socket: str = "default"
    timeout: float = 0.1


@dataclass(kw_only=True)
class ExpectClose:
    """Assert a server-initiated close on an already connected socket."""

    code: int
    socket: str = "default"
    timeout: float = 1.0


@dataclass(kw_only=True)
class Disconnect:
    """Close a client socket before subsequent scenario steps."""

    socket: str = "default"


@dataclass
class ChannelContext:
    """Expose live sockets and the layer to custom async assertions or actions."""

    sockets: dict[str, WebsocketCommunicator]
    layer: InMemoryChannelLayer


@dataclass(kw_only=True)
class ChannelAction:
    """Execute a named async action for behavior beyond the built-in steps."""

    name: str
    execute: Callable[[ChannelContext], Awaitable[None]]


ChannelStep = (
    Connect
    | SendJson
    | PublishGroupEvent
    | ExpectJson
    | ExpectNoMessage
    | ExpectClose
    | Disconnect
    | ChannelAction
)


@dataclass(kw_only=True)
class ChannelScenario:
    """Describe one conversation with fresh sockets and an isolated memory layer.

    Synchronous hooks run through database_sync_to_async so they may use the ORM.
    Database writes are not rolled back between scenarios; hooks must clean up
    mutable fixtures when later scenarios depend on them.
    """

    name: str
    steps: list[ChannelStep]
    prepare: Callable[[], None] | None = None
    cleanup: Callable[[], None] | None = None


class BloomerpChannelTestCase(TransactionTestCase):
    """Execute declarative channel scenarios while retaining communicator helpers."""

    registry: BloomerpRouteRegistry | None = None

    def websocket_application(self, registry: BloomerpRouteRegistry) -> URLRouter:
        """Build an ASGI application using the selected registry's socket routes."""
        return URLRouter(registry.create_websocket_url_patterns())

    def websocket_communicator(
        self,
        registry: BloomerpRouteRegistry,
        path: str,
        *,
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> WebsocketCommunicator:
        """Create a client communicator for a routed socket endpoint."""
        return WebsocketCommunicator(
            self.websocket_application(registry),
            path,
            headers=headers,
        )

    def get_test_scenarios(self) -> list[ChannelScenario]:
        """Return the ordered conversations declared by a concrete test case."""
        return []

    async def test_channel_scenarios(self) -> None:
        """Run each conversation as a named subtest on a fresh channel layer."""
        scenarios = await database_sync_to_async(self.get_test_scenarios)()
        for scenario in scenarios:
            with self.subTest(name=scenario.name):
                await self._run_channel_scenario(scenario)

    async def _run_channel_scenario(self, scenario: ChannelScenario) -> None:
        """Run one conversation and always release sockets and fixture hooks."""
        with override_settings(
            CHANNEL_LAYERS={
                "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
            }
        ):
            layer = get_channel_layer()
            assert isinstance(layer, InMemoryChannelLayer)
            context = ChannelContext(sockets={}, layer=layer)
            try:
                if scenario.prepare:
                    await database_sync_to_async(scenario.prepare)()
                for index, step in enumerate(scenario.steps, start=1):
                    label = (
                        step.name
                        if isinstance(step, ChannelAction)
                        else type(step).__name__
                    )
                    try:
                        await self._run_channel_step(step, context)
                    except Exception as exc:
                        raise AssertionError(
                            f"Scenario {scenario.name!r}, step {index} ({label}): {exc}"
                        ) from exc
            finally:
                try:
                    # Attempt every disconnect, even when one consumer crashed.
                    errors = await asyncio.gather(
                        *(
                            communicator.disconnect()
                            for communicator in context.sockets.values()
                        ),
                        return_exceptions=True,
                    )
                    if sys.exception() is None:
                        for error in errors:
                            if isinstance(error, BaseException):
                                raise error
                finally:
                    if scenario.cleanup:
                        await database_sync_to_async(scenario.cleanup)()

    async def _run_channel_step(
        self,
        step: ChannelStep,
        context: ChannelContext,
    ) -> None:
        """Execute a typed socket step and assert its observable result."""
        if isinstance(step, Connect):
            if self.registry is None:
                raise ValueError("Channel scenarios require a route registry")
            if step.socket in context.sockets:
                raise ValueError(f"Socket {step.socket!r} is already defined")
            if step.accepted and step.close_code is not None:
                raise ValueError(
                    "An accepted connection cannot specify a rejection code"
                )
            communicator = self.websocket_communicator(
                self.registry,
                step.path,
                headers=step.headers,
            )
            communicator.scope["user"] = (
                step.user if step.user is not None else AnonymousUser()
            )
            context.sockets[step.socket] = communicator
            accepted, detail = await communicator.connect(timeout=step.timeout)
            self.assertEqual(accepted, step.accepted)
            if accepted:
                self.assertEqual(detail, step.subprotocol)
            elif step.close_code is not None:
                self.assertEqual(detail, step.close_code)
        elif isinstance(step, PublishGroupEvent):
            await context.layer.group_send(step.group, step.event)
        elif isinstance(step, ChannelAction):
            await step.execute(context)
        else:
            communicator = context.sockets[step.socket]
            if isinstance(step, SendJson):
                await communicator.send_json_to(step.payload)
            elif isinstance(step, ExpectJson):
                payload = await communicator.receive_json_from(timeout=step.timeout)
                if step.payload is EXPECTED_JSON_UNSET and not step.validators:
                    raise ValueError("ExpectJson requires a payload or validators")
                if step.payload is not EXPECTED_JSON_UNSET:
                    self.assertEqual(payload, step.payload)
                for validator in step.validators:
                    self.assertTrue(
                        validator(payload),
                        f"Message validator {getattr(validator, '__name__', type(validator).__name__)} failed",
                    )
            elif isinstance(step, ExpectNoMessage):
                self.assertTrue(
                    await communicator.receive_nothing(timeout=step.timeout)
                )
            elif isinstance(step, ExpectClose):
                message = await communicator.receive_output(timeout=step.timeout)
                self.assertEqual(message["type"], "websocket.close")
                self.assertEqual(message["code"], step.code)
            elif isinstance(step, Disconnect):
                await communicator.disconnect()
