"""Bounded Streamable HTTP MCP sessions using the outbound public HTTPS transport."""

from __future__ import annotations

import json
import time
from types import TracebackType
from typing import Any, NoReturn, Self

import httpx

from bloomerp.services.mcp.oauth import (
    MCPAuthenticationError,
    PublicHTTPTransport,
    validate_remote_url,
)

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
MAX_RESPONSE_BYTES = 1_048_576
MAX_REQUEST_BYTES = 1_048_576
MAX_SESSION_SECONDS = 30
MAX_TOOLS = 500
MAX_CATALOG_PAGES = 10


class MCPUnavailableError(Exception):
    """Carry a safe, actionable external integration failure without remote error bodies."""


def reject_json_constant(value: str) -> NoReturn:
    """Reject non-finite values that JSON-RPC and persistent runtime contracts cannot carry."""
    raise ValueError("Non-finite JSON value")


class RemoteMcpSession:
    """Initialize one short-lived MCP session; never retry an uncertain tools/call."""

    def __init__(
        self,
        endpoint: str,
        authorization: str | None = None,
        *,
        deadline: float | None = None,
    ) -> None:
        """Retain private auth only in transport state, outside catalogs and runtime inputs."""
        try:
            validate_remote_url(endpoint)
        except MCPAuthenticationError:
            raise MCPUnavailableError(
                "External MCP tools require a public HTTPS endpoint without embedded credentials."
            ) from None
        self.endpoint = endpoint
        self.headers = {
            "Accept": "application/json, text/event-stream",
            "Accept-Encoding": "identity",
        }
        if authorization:
            self.headers["Authorization"] = authorization
        self.client: httpx.Client | None = None
        self.next_id = 0
        self.started_at = time.monotonic()
        self.deadline = deadline or self.started_at + MAX_SESSION_SECONDS
        self.has_tools = False
        self.remote_tool_names: dict[str, str] = {}

    def __enter__(self) -> Self:
        """Negotiate capabilities and session/protocol headers before any tool requests."""
        self.client = httpx.Client(
            transport=PublicHTTPTransport(),
            timeout=10,
            follow_redirects=False,
            trust_env=False,
        )
        try:
            result = self.request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSIONS[0],
                    "capabilities": {},
                    "clientInfo": {"name": "Bloomerp agents", "version": "1"},
                },
            )
            version = result.get("protocolVersion")
            if version not in PROTOCOL_VERSIONS:
                raise MCPUnavailableError(
                    "The MCP server negotiated an unsupported protocol version."
                )
            capabilities = result.get("capabilities")
            if not isinstance(capabilities, dict):
                raise MCPUnavailableError(
                    "The MCP server returned invalid capabilities."
                )
            self.has_tools = "tools" in capabilities
            self.headers["MCP-Protocol-Version"] = version
            self.request("notifications/initialized", notification=True)
            return self
        except Exception:
            self.close()
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release the remote session and sockets without overriding a tool's recorded outcome."""
        self.close()

    def close(self) -> None:
        """Best-effort terminate a session without retrying or surfacing cleanup failures."""
        if self.client is not None:
            if "MCP-Session-Id" in self.headers:
                try:
                    with self.client.stream(
                        "DELETE", self.endpoint, headers=self.headers, timeout=2
                    ):
                        pass
                except (httpx.HTTPError, MCPAuthenticationError, OSError):
                    pass
            self.client.close()
            self.client = None

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        notification: bool = False,
    ) -> dict[str, Any]:
        """Read a matching JSON or SSE JSON-RPC reply within fixed byte and elapsed limits."""
        if self.client is None:
            raise MCPUnavailableError("The MCP session is not initialized.")
        if time.monotonic() >= self.deadline:
            raise MCPUnavailableError("The MCP server took too long. Try again.")
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            self.next_id += 1
            message["id"] = self.next_id
        payload = json.dumps(message, allow_nan=False).encode()
        if len(payload) > MAX_REQUEST_BYTES:
            raise MCPUnavailableError("The MCP tool request exceeds the allowed size.")
        try:
            with self.client.stream(
                "POST",
                self.endpoint,
                headers={**self.headers, "Content-Type": "application/json"},
                content=payload,
                timeout=min(10, max(0.01, self.deadline - time.monotonic())),
            ) as response:
                if response.status_code in {401, 403}:
                    raise MCPUnavailableError(
                        "The MCP server rejected this connection. Reconnect the integration."
                    )
                if not response.is_success:
                    raise MCPUnavailableError(
                        f"The MCP server returned HTTP {response.status_code}. Check the integration endpoint or reconnect."
                    )
                if notification:
                    if response.status_code not in {202, 204}:
                        raise MCPUnavailableError(
                            "The MCP server did not accept initialization."
                        )
                    return {}
                if method == "initialize":
                    session_id = response.headers.get("MCP-Session-Id")
                    if session_id is not None:
                        if (
                            not session_id
                            or len(session_id) > 512
                            or any(not 0x21 <= ord(char) <= 0x7E for char in session_id)
                        ):
                            raise MCPUnavailableError(
                                "The MCP server returned an invalid session identifier."
                            )
                        self.headers["MCP-Session-Id"] = session_id
                if (
                    response.headers.get("Content-Encoding", "identity").lower()
                    != "identity"
                ):
                    raise MCPUnavailableError(
                        "The MCP server returned an unsupported compressed response."
                    )
                content_type = (
                    response.headers.get("Content-Type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if content_type not in {"application/json", "text/event-stream"}:
                    raise MCPUnavailableError(
                        "The MCP server must return JSON or SSE responses."
                    )
                buffer = bytearray()
                received = 0
                for chunk in response.iter_raw():
                    received += len(chunk)
                    if (
                        received > MAX_RESPONSE_BYTES
                        or time.monotonic() >= self.deadline
                    ):
                        raise MCPUnavailableError(
                            "The MCP response exceeded its size or time limit."
                        )
                    buffer.extend(chunk)
                    if content_type == "text/event-stream":
                        # Normalize CRLF only after complete lines arrive; raw chunks may split UTF-8.
                        normalized = bytes(buffer).replace(b"\r\n", b"\n")
                        while b"\n\n" in normalized:
                            event, normalized = normalized.split(b"\n\n", 1)
                            data = b"\n".join(
                                line[5:].lstrip(b" ")
                                for line in event.split(b"\n")
                                if line.startswith(b"data:")
                            )
                            if data:
                                reply = self.sse_reply(data, message["id"], method)
                                if reply is not None:
                                    return reply
                        buffer = bytearray(normalized)
                if content_type == "application/json":
                    reply = self.decode_reply(bytes(buffer), message["id"], method)
                    if reply is not None:
                        return reply
                raise MCPUnavailableError(
                    "The MCP response ended without a matching result. The tool outcome may be uncertain."
                )
        except (httpx.HTTPError, OSError, MCPAuthenticationError):
            raise MCPUnavailableError(
                "The MCP server could not be reached securely. Check the endpoint and reconnect if necessary."
            ) from None

    def sse_reply(
        self, data: bytes, request_id: int, method: str
    ) -> dict[str, Any] | None:
        """Respond to server pings and reject unsupported capabilities while awaiting a tool reply."""
        try:
            message = json.loads(data, parse_constant=reject_json_constant)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise MCPUnavailableError("The MCP server returned invalid JSON.") from None
        if (
            isinstance(message, dict)
            and message.get("jsonrpc") == "2.0"
            and "method" in message
            and "id" in message
        ):
            server_id = message["id"]
            if type(server_id) not in {str, int}:
                raise MCPUnavailableError(
                    "The MCP server returned an invalid request identifier."
                )
            response: dict[str, Any] = {"jsonrpc": "2.0", "id": server_id}
            if message["method"] == "ping":
                response["result"] = {}
            else:
                response["error"] = {
                    "code": -32601,
                    "message": "This client does not provide that capability.",
                }
            if self.client is None or time.monotonic() >= self.deadline:
                raise MCPUnavailableError(
                    "The MCP session expired before responding to the server."
                )
            with self.client.stream(
                "POST",
                self.endpoint,
                headers={**self.headers, "Content-Type": "application/json"},
                content=json.dumps(response).encode(),
                timeout=min(10, max(0.01, self.deadline - time.monotonic())),
            ) as accepted:
                if accepted.status_code not in {202, 204}:
                    raise MCPUnavailableError(
                        "The MCP server rejected a client protocol response."
                    )
            return None
        return self.decode_reply(data, request_id, method)

    @staticmethod
    def decode_reply(
        data: bytes, request_id: int, method: str
    ) -> dict[str, Any] | None:
        """Ignore notifications and reject unsupported server requests without exposing error text."""
        try:
            value = json.loads(data, parse_constant=reject_json_constant)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise MCPUnavailableError("The MCP server returned invalid JSON.") from None
        if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
            raise MCPUnavailableError(
                "The MCP server returned an invalid JSON-RPC response."
            )
        if "method" in value:
            if "id" in value:
                raise MCPUnavailableError(
                    "The MCP server requires unsupported client capabilities."
                )
            return None
        if type(value.get("id")) is not int or value["id"] != request_id:
            return None
        if "error" in value:
            raise MCPUnavailableError(
                f"The MCP server rejected {method}. Check its configuration and permissions."
            )
        result = value.get("result")
        if not isinstance(result, dict):
            raise MCPUnavailableError("The MCP server returned an invalid result.")
        return result

    def catalog(self) -> list[dict[str, Any]]:
        """Read bounded paginated tool definitions without granting unsupported capabilities."""
        if not self.has_tools:
            return []
        tools: list[dict[str, Any]] = []
        cursor = None
        seen = set()
        names = set()
        for _ in range(MAX_CATALOG_PAGES):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            page = result.get("tools")
            if not isinstance(page, list):
                raise MCPUnavailableError(
                    "The MCP server returned an invalid tool catalog."
                )
            for tool in page:
                if (
                    not isinstance(tool, dict)
                    or not isinstance(tool.get("name"), str)
                    or not tool["name"]
                    or len(tool["name"]) > 255
                    or tool["name"] in names
                    or not isinstance(tool.get("inputSchema"), dict)
                ):
                    raise MCPUnavailableError(
                        "The MCP server returned an invalid or duplicate tool definition."
                    )
                names.add(tool["name"])
                tools.append(tool)
                if len(tools) > MAX_TOOLS:
                    raise MCPUnavailableError(
                        "The MCP server advertised too many tools."
                    )
            cursor = result.get("nextCursor")
            if cursor is None:
                return tools
            if (
                not isinstance(cursor, str)
                or not cursor
                or len(cursor) > 4096
                or cursor in seen
            ):
                raise MCPUnavailableError(
                    "The MCP server returned invalid catalog pagination."
                )
            seen.add(cursor)
        raise MCPUnavailableError("The MCP tool catalog exceeded its page limit.")
