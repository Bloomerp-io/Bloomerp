"""Verify the controller transport boundary without providers or database writes."""

from types import SimpleNamespace
from unittest.mock import create_autospec, patch
from uuid import uuid4

from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, override_settings
from django.urls import path

from bloomerp.agents.controller import (
    AgentController,
    AgentReplayPage,
    AgentSubmission,
)
from bloomerp.channels.agents.agent_consumer import AgentConsumer
from bloomerp.config.definition import BloomerpConfig


@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class AgentConsumerTests(SimpleTestCase):
    """Exercise real socket routing while replacing only controller operations."""

    async def connect_browser(self) -> WebsocketCommunicator:
        """Connect an authenticated tab and consume its initial acknowledgement."""
        self.tab_id = uuid4()
        self.user = SimpleNamespace(pk=1, is_authenticated=True)
        app = URLRouter([path("ws/agents/<uuid:tab_id>/", AgentConsumer.as_asgi())])
        browser = WebsocketCommunicator(
            app,
            f"/ws/agents/{self.tab_id}/",
            headers=[(b"host", b"erp.test"), (b"origin", b"https://erp.test")],
        )
        browser.scope["user"] = self.user
        connected, _ = await browser.connect()
        self.assertTrue(connected)
        self.assertEqual(
            (await browser.receive_json_from())["type"], "connection.ready"
        )
        return browser

    async def test_submission_binds_socket_identity(self) -> None:
        """Use the socket actor and tab despite conflicting client page hints."""
        controller = create_autospec(AgentController, instance=True)
        conversation_id, run_id, message_id = uuid4(), uuid4(), uuid4()
        controller.execute.return_value = AgentSubmission(
            conversation_id=conversation_id,
            run_id=run_id,
            message_id=message_id,
            disposition="steered",
        )
        with patch(
            "bloomerp.channels.agents.agent_consumer.AgentController",
            return_value=controller,
        ) as factory:
            browser = await self.connect_browser()
            try:
                await browser.send_json_to(
                    {
                        "type": "tab.state",
                        "page": {
                            "page_id": "invoices",
                            "url": "/invoices/",
                            "title": "Invoices",
                        },
                    }
                )
                await browser.receive_json_from()
                await browser.send_json_to(
                    {
                        "type": "chat.message",
                        "message": "",
                        "attachments": ["signed-selection"],
                        "conversation_id": str(conversation_id),
                        "client_message_id": str(message_id),
                        "active_run_behavior": "steer",
                        "approval_rules": {"default": "never"},
                        "page": {"tab_id": str(uuid4()), "page_id": "forged"},
                    }
                )
                response = await browser.receive_json_from()
                self.assertEqual(response["status"], "accepted")
                self.assertEqual(response["run_id"], str(run_id))
                request = controller.execute.await_args.args[0]
                self.assertEqual(request.conversation_id, conversation_id)
                self.assertEqual(request.client_message_id, message_id)
                self.assertEqual(request.active_run_behavior, "steer")
                self.assertEqual(request.approval_rules.default, "never")
                self.assertEqual(request.attachments, ["signed-selection"])
                self.assertEqual(request.browser_context.tab_id, self.tab_id)
                self.assertEqual(request.browser_context.page_id, "invoices")
                factory.assert_called_once_with(
                    self.user, tab_id=self.tab_id, origin="https://erp.test"
                )
            finally:
                await browser.disconnect()
            controller.cancel.assert_not_awaited()

    async def test_invalid_input_never_reaches_controller(self) -> None:
        """Reject malformed identifiers, blank messages, actor overrides, and unbounded replay."""
        controller = create_autospec(AgentController, instance=True)
        with patch(
            "bloomerp.channels.agents.agent_consumer.AgentController",
            return_value=controller,
        ):
            browser = await self.connect_browser()
            try:
                for payload in (
                    {"type": "chat.message", "message": " "},
                    {"type": "chat.message", "message": "Hi", "conversation_id": "bad"},
                    {"type": "chat.message", "message": "Hi", "user_id": 2},
                    {
                        "type": "chat.message",
                        "message": "Hi",
                        "approval_rules": {"default": "invalid"},
                    },
                    {
                        "type": "chat.replay",
                        "conversation_id": str(uuid4()),
                        "run_id": str(uuid4()),
                        "limit": 501,
                    },
                ):
                    await browser.send_json_to(payload)
                    self.assertEqual(
                        (await browser.receive_json_from())["type"], "protocol.error"
                    )
                controller.execute.assert_not_awaited()
                controller.replay.assert_not_awaited()
            finally:
                await browser.disconnect()

    async def test_run_commands_and_replay(self) -> None:
        """Forward validated lifecycle commands and serialize controller responses."""
        controller = create_autospec(AgentController, instance=True)
        conversation_id, run_id, approval_id = uuid4(), uuid4(), uuid4()
        controller.resume.return_value = AgentSubmission(
            conversation_id=conversation_id,
            run_id=run_id,
            disposition="resumed",
        )
        controller.replay.return_value = AgentReplayPage(
            events=(), next_sequence=7, has_more=False
        )
        with patch(
            "bloomerp.channels.agents.agent_consumer.AgentController",
            return_value=controller,
        ):
            browser = await self.connect_browser()
            try:
                for action in ("chat.resume", "chat.cancel"):
                    await browser.send_json_to({"type": action, "run_id": str(run_id)})
                    self.assertEqual(
                        (await browser.receive_json_from())["status"], "accepted"
                    )
                controller.resume.assert_awaited_once_with(run_id)
                controller.cancel.assert_awaited_once_with(run_id)
                await browser.send_json_to(
                    {
                        "type": "chat.approval",
                        "approval_id": str(approval_id),
                        "decision": "rejected",
                    }
                )
                self.assertEqual(
                    (await browser.receive_json_from())["status"], "accepted"
                )
                self.assertEqual(
                    controller.decide_approval.await_args.args[0].approval_id,
                    approval_id,
                )
                await browser.send_json_to(
                    {
                        "type": "chat.replay",
                        "conversation_id": str(conversation_id),
                        "run_id": str(run_id),
                        "after_sequence": 7,
                    }
                )
                response = await browser.receive_json_from()
                self.assertEqual(response["next_sequence"], 7)
                self.assertEqual(response["events"], [])
                self.assertEqual(controller.replay.await_args.args[0].run_id, run_id)
                controller.cancel.side_effect = PermissionDenied("Private details")
                await browser.send_json_to(
                    {"type": "chat.cancel", "run_id": str(run_id)}
                )
                response = await browser.receive_json_from()
                self.assertEqual(response["status"], "forbidden")
                self.assertNotIn("Private details", str(response))
            finally:
                await browser.disconnect()

    @override_settings(BLOOMERP_CONFIG=BloomerpConfig(bloomai_settings=None))
    async def test_unconfigured_controller_keeps_socket_alive(self) -> None:
        """Report missing instance configuration without breaking browser transport."""
        browser = await self.connect_browser()
        try:
            await browser.send_json_to({"type": "chat.message", "message": "Hi"})
            self.assertEqual(
                (await browser.receive_json_from())["status"], "unavailable"
            )
            await browser.send_json_to(
                {
                    "type": "tab.state",
                    "page": {
                        "page_id": "home",
                        "url": "/",
                        "title": "Home",
                    },
                }
            )
            self.assertEqual(
                (await browser.receive_json_from())["type"], "tab.registered"
            )
        finally:
            await browser.disconnect()
