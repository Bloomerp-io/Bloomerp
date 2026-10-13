"""Exercise MCP transport, live tab discovery, and websocket navigation together."""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.http import HttpResponse
from django.test import SimpleTestCase, override_settings
from django.urls import path
from django.views import View
from rest_framework.test import APIRequestFactory, force_authenticate

from bloomerp.channels.agents.agent_consumer import AgentConsumer
from bloomerp.channels.agents.events import (
    BrowserTab, discover_browser_tabs, navigate_browser_tab, navigate_browser_tabs,
)
from bloomerp.mcp.view import McpEndpointView
from bloomerp.router import BloomerpRouteRegistry, router
from bloomerp.views.mcp import navigate_user, view_pages  # noqa: F401


class ExamplePage(View):
    """Supply a page with an observable permission gate for catalog tests."""

    def has_permission(self) -> bool:
        """Restrict page discovery to staff in this fixture."""
        return self.request.user.is_staff

    def get(self, request: Any) -> HttpResponse:
        """Return a harmless page for URL resolution."""
        return HttpResponse("Example")


urlpatterns = [
    path("example/", ExamplePage.as_view(), name="browser_example"),
    path("hidden/", ExamplePage.as_view(), name="browser_hidden"),
    path("api/example/", ExamplePage.as_view(), name="browser_api"),
    path("example/<int:pk>/", ExamplePage.as_view(), name="browser_detail"),
]


@override_settings(
    ROOT_URLCONF=__name__, ALLOWED_HOSTS=["erp.test"],
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class BrowserMcpToolsTests(SimpleTestCase):
    """Verify caller isolation and browser acknowledgements through the real transport."""

    def setUp(self) -> None:
        """Install a small route catalog without querying application models."""
        self.registry = BloomerpRouteRegistry()
        for route_name, route_path, route_type, searchable in (
            ("browser_example", "example/", "app", True),
            ("browser_hidden", "hidden/", "app", False),
            ("browser_api", "api/example/", "api", True),
            ("browser_detail", "example/<int:pk>/", "app", True),
        ):
            self.registry.register(
                path=route_path, name="Example page", url_name=route_name,
                route_type=route_type, searchable=searchable,
            )(ExamplePage)
        tool_routes = [
            route for route in router.routes if route.url_name in {"view_pages", "navigate_user_mcp"}
        ]
        self.assertEqual(len(tool_routes), 2)
        self.enterContext(patch.object(router, "get_routes", return_value=self.registry.routes))
        self.enterContext(patch.object(router, "get_mcp_routes", return_value=tool_routes))

    def call_tool(
        self, name: str, arguments: dict[str, Any], user_id: int = 1, staff: bool = True,
    ) -> dict[str, Any]:
        """Send a real MCP tool call with a linked user and the public HTTPS origin."""
        request = APIRequestFactory().post(
            "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": name, "arguments": arguments}},
            format="json", secure=True, HTTP_HOST="erp.test",
            HTTP_ACCEPT="application/json, text/event-stream",
        )
        force_authenticate(request, user=SimpleNamespace(
            pk=user_id, is_authenticated=True, is_staff=staff,
        ))
        response = McpEndpointView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        return response.data["result"]

    async def connect_browser(self, user_id: int, tab_id: str) -> WebsocketCommunicator:
        """Register a browser session with a known page version and same-origin headers."""
        application = URLRouter([
            path("ws/agents/<uuid:tab_id>/", AgentConsumer.as_asgi()),
        ])
        browser = WebsocketCommunicator(
            application, f"/ws/agents/{tab_id}/",
            headers=[(b"host", b"erp.test"), (b"origin", b"https://erp.test")],
        )
        browser.scope["user"] = SimpleNamespace(pk=user_id, is_authenticated=True)
        connected, _ = await browser.connect()
        self.assertTrue(connected)
        self.assertEqual((await browser.receive_json_from())["type"], "connection.ready")
        await browser.send_json_to({"type": "tab.state", "page": {
            "page_id": "page-1", "url": "https://erp.test/example/", "title": "Example",
            "visible": True, "focused": True,
        }})
        self.assertEqual((await browser.receive_json_from())["type"], "tab.registered")
        return browser

    async def test_mcp_discovers_pages_and_navigates_only_the_selected_users_tab(self) -> None:
        """Discover a page and route one acknowledged command across HTTP and Channels."""
        first_id, second_id = str(uuid4()), str(uuid4())
        first = await self.connect_browser(1, first_id)
        second = await self.connect_browser(2, second_id)
        try:
            catalog = await sync_to_async(self.call_tool)("view_pages", {"search": "EXAMPLE"})
            payload = catalog["structuredContent"]
            self.assertEqual([page["url"] for page in payload["pages"]], ["/example/"])
            self.assertEqual([tab["tab_id"] for tab in payload["browser_tabs"]], [first_id])
            self.assertNotIn("channel_name", payload["browser_tabs"][0])
            task = asyncio.create_task(sync_to_async(self.call_tool)(
                "navigate_user_mcp", {"url": "https://erp.test/example/?q=one#card"},
            ))
            command = await first.receive_json_from(timeout=2)
            self.assertEqual(command["action"], "navigate")
            self.assertEqual(command["arguments"]["url"], "/example/?q=one#card")
            self.assertEqual(command["page_id"], "page-1")
            await first.send_json_to({
                "type": "command.result", "command_id": command["command_id"],
                "status": "accepted", "result": {"url": "https://erp.test/example/?q=one#card"},
            })
            result = (await task)["structuredContent"]
            self.assertEqual(result["status"], "accepted")
            self.assertTrue(result["success"])
            self.assertTrue(await second.receive_nothing(timeout=0.05))
            denied = await sync_to_async(self.call_tool)(
                "navigate_user_mcp", {"url": "/example/", "tab_id": second_id},
            )
            self.assertTrue(denied["isError"])
        finally:
            await first.disconnect()
            await second.disconnect()

    async def test_explicit_target_selects_one_tab_and_handles_failed_ack(self) -> None:
        """Select only the named tab and surface stale-page browser errors."""
        first_id, second_id = str(uuid4()), str(uuid4())
        first = await self.connect_browser(1, first_id)
        second = await self.connect_browser(1, second_id)
        try:
            task = asyncio.create_task(sync_to_async(self.call_tool)(
                "navigate_user_mcp", {"url": "/example/", "tab_id": second_id},
            ))
            command = await second.receive_json_from(timeout=2)
            await second.send_json_to({
                "type": "command.result", "command_id": command["command_id"],
                "status": "failed", "result": {"message": "Page has changed"},
            })
            self.assertTrue((await task)["isError"])
            self.assertTrue(await first.receive_nothing(timeout=0.05))
        finally:
            await first.disconnect()
            await second.disconnect()

    async def test_omitted_tab_id_navigates_every_connection_including_duplicate_tab_ids(self) -> None:
        """Broadcast to each of the caller's connections while isolating other users."""
        shared_id = str(uuid4())
        first = await self.connect_browser(1, shared_id)
        second = await self.connect_browser(1, shared_id)
        other = await self.connect_browser(2, str(uuid4()))
        try:
            task = asyncio.create_task(sync_to_async(self.call_tool)(
                "navigate_user_mcp", {"url": "/example/"},
            ))
            commands = await asyncio.gather(first.receive_json_from(), second.receive_json_from())
            self.assertNotEqual(commands[0]["command_id"], commands[1]["command_id"])
            for browser, command in zip((first, second), commands):
                self.assertEqual(command["arguments"]["url"], "/example/")
                await browser.send_json_to({
                    "type": "command.result", "command_id": command["command_id"],
                    "status": "accepted", "result": {},
                })
            response = (await task)["structuredContent"]
            self.assertTrue(response["success"])
            self.assertEqual(response["status"], "accepted")
            self.assertEqual(len(response["results"]), 2)
            self.assertEqual({result["tab_id"] for result in response["results"]}, {shared_id})
            self.assertTrue(await other.receive_nothing(timeout=0.05))
        finally:
            await first.disconnect()
            await second.disconnect()
            await other.disconnect()

    async def test_broadcast_reports_partial_failure_without_discarding_success(self) -> None:
        """Keep individual browser errors alongside acknowledgements from healthy tabs."""
        first = await self.connect_browser(1, str(uuid4()))
        second = await self.connect_browser(1, str(uuid4()))
        try:
            task = asyncio.create_task(sync_to_async(self.call_tool)(
                "navigate_user_mcp", {"url": "/example/"},
            ))
            commands = await asyncio.gather(first.receive_json_from(), second.receive_json_from())
            for browser, command, status in zip((first, second), commands, ("accepted", "failed")):
                await browser.send_json_to({
                    "type": "command.result", "command_id": command["command_id"],
                    "status": status, "result": {},
                })
            response = await task
            self.assertNotIn("isError", response)
            self.assertFalse(response["structuredContent"]["success"])
            self.assertEqual(response["structuredContent"]["status"], "partial")
            self.assertEqual(
                {result["status"] for result in response["structuredContent"]["results"]},
                {"accepted", "failed"},
            )
        finally:
            await first.disconnect()
            await second.disconnect()

    async def test_delivery_exception_does_not_prevent_other_tabs_from_navigating(self) -> None:
        """Convert an individual channel failure into a result without losing other replies."""
        tabs = [BrowserTab(str(uuid4()), "first", {}), BrowserTab(str(uuid4()), "second", {})]
        accepted = {"success": True, "status": "accepted", "tab_id": tabs[1].tab_id}
        with patch("bloomerp.channels.agents.events.navigate_browser_tab", new=AsyncMock(
            side_effect=[RuntimeError("Disconnected"), accepted],
        )):
            results = await navigate_browser_tabs(tabs, "/example/")
        self.assertEqual(results[0]["status"], "failed")
        self.assertEqual(results[1], accepted)

    def test_no_connected_tabs_returns_clear_error(self) -> None:
        """Reject navigation when the authenticated caller has no browser connection."""
        response = self.call_tool("navigate_user_mcp", {"url": "/example/"})
        self.assertTrue(response["isError"])
        self.assertIn("Open Bloomerp in a browser", response["content"][0]["text"])

    async def test_unacknowledged_command_reports_dispatch_only(self) -> None:
        """Do not claim browser acceptance when no matching acknowledgement arrives."""
        browser = await self.connect_browser(1, str(uuid4()))
        try:
            tabs = await discover_browser_tabs(1, timeout=0.05)
            result = await navigate_browser_tab(tabs[0], "/example/", timeout=0.05)
            self.assertEqual(result["status"], "dispatched")
        finally:
            await browser.disconnect()

    def test_hides_permission_denied_pages_and_rejects_non_ui_urls(self) -> None:
        """Filter view permission gates and reject external, relative, API, and unknown URLs."""
        catalog = self.call_tool("view_pages", {}, staff=False)
        self.assertEqual(catalog["structuredContent"]["pages"], [])
        for url in ("https://other.test/example/", "//erp.test/example/", "javascript:alert(1)",
                    "example/", "/api/example/", "/missing/", "http://erp.test/example/"):
            with self.subTest(url=url):
                self.assertTrue(self.call_tool("navigate_user_mcp", {"url": url})["isError"])

    async def test_rejects_anonymous_and_cross_origin_browser_connections(self) -> None:
        """Prevent anonymous or cross-origin session-authenticated browser control."""
        application = URLRouter([path("ws/agents/<uuid:tab_id>/", AgentConsumer.as_asgi())])
        for authenticated, origin, code in ((False, b"https://erp.test", 4401),
                                            (True, b"https://other.test", 4403)):
            browser = WebsocketCommunicator(
                application, f"/ws/agents/{uuid4()}/",
                headers=[(b"host", b"erp.test"), (b"origin", origin)],
            )
            browser.scope["user"] = SimpleNamespace(pk=1, is_authenticated=authenticated)
            self.assertEqual(await browser.connect(), (False, code))
            await browser.disconnect()
