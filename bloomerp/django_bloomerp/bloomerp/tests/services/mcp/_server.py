"""Deterministic Streamable HTTP server transport for tests without remote accounts."""

from __future__ import annotations

import json
from typing import Any

import httpx


class ProtocolServer:
    """Model initialization, authenticated sessions, tool catalogs and uncertain effects."""

    def __init__(self) -> None:
        """Initialize independently mutable catalog, responses and observation state."""
        self.tools: list[dict[str, Any]] = [
            {
                "name": "fixture_effect",
                "title": "Remote effect",
                "inputSchema": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            }
        ]
        self.result: dict[str, Any] = {
            "content": [{"type": "text", "text": "Done"}],
            "structuredContent": {"value": 7},
            "_meta": {"remote": "preserved"},
        }
        self.requests: list[httpx.Request] = []
        self.effects: list[dict[str, Any]] = []
        self.sessions: dict[str, str | None] = {}
        self.sse = False
        self.lose_result = False
        self.status = 200
        self.rpc_error = False
        self.version = "2025-11-25"
        self.pages: dict[str | None, dict[str, Any]] = {}
        self.server_requests: list[str] = []
        self.client_responses: list[dict[str, Any]] = []

    def response(
        self,
        request: httpx.Request,
        value: dict[str, Any],
        *,
        session_id: str | None = None,
    ) -> httpx.Response:
        """Return unconsumed JSON or SSE bytes as a real streaming transport would."""
        headers = {
            "Content-Type": "text/event-stream" if self.sse else "application/json"
        }
        if session_id:
            headers["MCP-Session-Id"] = session_id
        data = json.dumps(value).encode()
        if self.sse:
            data = (
                b': keepalive\r\ndata:\r\n\r\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\r\n\r\ndata: '
                + data
                + b"\r\n\r\n"
            )
            if json.loads(request.content).get("method") in {
                "tools/list",
                "tools/call",
            }:
                for method in self.server_requests:
                    message = {
                        "jsonrpc": "2.0",
                        "id": "server-" + method,
                        "method": method,
                        "params": {},
                    }
                    data = b"data: " + json.dumps(message).encode() + b"\n\n" + data
        return httpx.Response(
            200, headers=headers, stream=httpx.ByteStream(data), request=request
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Apply fixture effects only after the expected MCP lifecycle and session headers."""
        self.requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(204, request=request)
        if self.status != 200:
            return httpx.Response(self.status, request=request)
        message = json.loads(request.content)
        if "method" not in message:
            self.client_responses.append(message)
            return httpx.Response(202, request=request)
        method = message["method"]
        if method == "initialize":
            session = f"session-{len(self.sessions) + 1}"
            self.sessions[session] = request.headers.get("Authorization")
            return self.response(
                request,
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {
                        "protocolVersion": self.version,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "Test", "version": "1"},
                    },
                },
                session_id=session,
            )
        session_id = request.headers.get("MCP-Session-Id")
        if (
            session_id not in self.sessions
            or request.headers.get("Authorization") != self.sessions[session_id]
            or request.headers.get("MCP-Protocol-Version") != self.version
        ):
            return httpx.Response(400, request=request)
        if method == "notifications/initialized":
            return httpx.Response(202, request=request)
        if self.rpc_error:
            return self.response(
                request,
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32603, "message": "unsafe-server-secret"},
                },
            )
        if method == "tools/list":
            result = self.pages.get(
                message.get("params", {}).get("cursor"), {"tools": self.tools}
            )
        elif method == "tools/call":
            self.effects.append(message["params"])
            if self.lose_result:
                raise httpx.ReadTimeout("unsafe-transport-secret", request=request)
            result = self.result
        else:
            return httpx.Response(400, request=request)
        return self.response(
            request, {"jsonrpc": "2.0", "id": message["id"], "result": result}
        )
