"""Bounded external MCP protocol tests against an in-memory HTTP transport."""

import json
from unittest.mock import patch

import httpx
from bloomerp.services.mcp.client import MCPUnavailableError, RemoteMcpSession
from bloomerp.tests.services.mcp._server import ProtocolServer
from django.test import SimpleTestCase


class TestRemoteMcpSession(SimpleTestCase):
    """Exercise initialization, negotiation, SSE, pagination and safe failures offline."""

    def setUp(self) -> None:
        """Replace only the network transport, retaining the actual protocol implementation."""
        self.server = ProtocolServer()
        self.enterContext(
            patch(
                "bloomerp.services.mcp.client.PublicHTTPTransport",
                side_effect=self.transport,
            )
        )

    def transport(self) -> httpx.MockTransport:
        """Construct an isolated HTTP transport for each real session."""
        return httpx.MockTransport(self.server.handle)

    def test_json_and_sse_preserve_results_and_headers(self) -> None:
        """Negotiate version and session IDs before listing and calling tools in either format."""
        for sse in (False, True):
            with self.subTest(sse=sse):
                self.server.sse = sse
                self.server.version = "2025-06-18"
                with RemoteMcpSession(
                    "https://tools.example.com/mcp", "Bearer fixture-secret"
                ) as session:
                    self.assertEqual(session.catalog(), self.server.tools)
                    self.assertEqual(
                        session.request(
                            "tools/call",
                            {"name": "fixture_effect", "arguments": {"value": 7}},
                        ),
                        self.server.result,
                    )
                self.assertEqual(self.server.requests[-1].method, "DELETE")
                for request in self.server.requests:
                    self.assertEqual(request.headers["Accept-Encoding"], "identity")

    def test_pagination_and_bounds(self) -> None:
        """Read paginated catalogs and reject repeated cursors rather than looping forever."""
        first = self.server.tools[0]
        second = {**first, "name": "second_tool"}
        self.server.pages = {
            None: {"tools": [first], "nextCursor": "next"},
            "next": {"tools": [second]},
        }
        with RemoteMcpSession("https://tools.example.com/mcp") as session:
            self.assertEqual(session.catalog(), [first, second])
        self.server.pages["next"] = {"tools": [], "nextCursor": "next"}
        with (
            RemoteMcpSession("https://tools.example.com/mcp") as session,
            self.assertRaisesMessage(MCPUnavailableError, "pagination"),
        ):
            session.catalog()

    def test_sse_pings_and_unsupported_server_capabilities(self) -> None:
        """Acknowledge pings and refuse sampling requests without blocking the requested tool response."""
        self.server.sse = True
        self.server.server_requests = ["ping", "sampling/createMessage"]
        with RemoteMcpSession("https://tools.example.com/mcp") as session:
            self.assertEqual(session.catalog(), self.server.tools)
        self.assertEqual(len(self.server.client_responses), 2)
        replies = {item["id"]: item for item in self.server.client_responses}
        self.assertEqual(replies["server-ping"]["result"], {})
        self.assertEqual(
            replies["server-sampling/createMessage"]["error"]["code"], -32601
        )

    def test_server_errors_and_transport_loss_do_not_leak_or_retry(self) -> None:
        """Use safe error text and dispatch an uncertain effect only once."""
        with RemoteMcpSession("https://tools.example.com/mcp") as session:
            self.server.rpc_error = True
            with self.assertRaisesMessage(
                MCPUnavailableError, "rejected tools/list"
            ) as failure:
                session.catalog()
            self.assertNotIn("unsafe-server-secret", str(failure.exception))
            self.server.rpc_error = False
            self.server.lose_result = True
            with self.assertRaisesMessage(
                MCPUnavailableError, "could not be reached"
            ) as failure:
                session.request(
                    "tools/call", {"name": "fixture_effect", "arguments": {"value": 7}}
                )
            self.assertNotIn("unsafe-transport-secret", str(failure.exception))
        self.assertEqual(len(self.server.effects), 1)

    def test_bad_protocol_authentication_and_private_endpoint(self) -> None:
        """Reject unsupported negotiation, rejected accounts and non-HTTPS endpoints."""
        self.server.version = "unsupported"
        with (
            self.assertRaisesMessage(MCPUnavailableError, "unsupported protocol"),
            RemoteMcpSession("https://tools.example.com/mcp"),
        ):
            pass
        self.server.status = 401
        with (
            self.assertRaisesMessage(MCPUnavailableError, "Reconnect"),
            RemoteMcpSession("https://tools.example.com/mcp"),
        ):
            pass
        with self.assertRaisesMessage(MCPUnavailableError, "public HTTPS"):
            RemoteMcpSession("http://localhost/mcp")

    def oversized_response(self, request: httpx.Request) -> httpx.Response:
        """Return a valid-shaped oversized response without relying on an external server."""
        message = json.loads(request.content)
        body = {
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {"oversized": "x" * 1_048_577},
        }
        return self.server.response(request, body)

    def test_response_limit_and_invalid_reply_shapes(self) -> None:
        """Stop oversized or malformed data before it enters runtime persistence."""
        with (
            patch(
                "bloomerp.services.mcp.client.PublicHTTPTransport",
                return_value=httpx.MockTransport(self.oversized_response),
            ),
            self.assertRaisesMessage(MCPUnavailableError, "size or time"),
            RemoteMcpSession("https://tools.example.com/mcp"),
        ):
            pass
        for invalid in (
            b"[]",
            b"not-json",
            b'{"jsonrpc":"2.0","id":1,"result":{"value":NaN}}',
        ):
            with self.subTest(reply=invalid), self.assertRaises(MCPUnavailableError):
                RemoteMcpSession.decode_reply(invalid, 1, "tools/list")
