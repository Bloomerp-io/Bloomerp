"""Channel-layer discovery and request/reply for authenticated browser tabs."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def agent_user_group_name(user_id: int | str) -> str:
    """Scope browser discovery to the authenticated user's active connections."""
    return f"agent.user.{user_id}"


def agent_tab_group_name(user_id: int | str, tab_id: str) -> str:
    """Build a user-scoped tab group for browser command publishers."""
    return f"agent.{user_id}.{UUID(tab_id).hex}"


@dataclass(frozen=True)
class BrowserTab:
    """Describe a live connection, retaining its channel only on the backend."""

    tab_id: str
    channel_name: str
    page: dict[str, Any]

    def public_state(self) -> dict[str, Any]:
        """Expose browser context without exposing Channels routing addresses."""
        return {"tab_id": self.tab_id, **self.page}


async def discover_browser_tabs(user_id: int | str, timeout: float = 0.3) -> list[BrowserTab]:
    """Probe live sockets through the shared layer without a stale presence cache."""
    layer = get_channel_layer()
    if layer is None:
        raise RuntimeError("No channel layer is configured")
    reply_channel = await layer.new_channel("agent.discovery.")
    await layer.group_send(agent_user_group_name(user_id), {
        "type": "agent.discover", "reply_channel": reply_channel,
    })
    tabs: dict[str, BrowserTab] = {}
    deadline = asyncio.get_running_loop().time() + timeout
    while (remaining := deadline - asyncio.get_running_loop().time()) > 0:
        try:
            reply = await asyncio.wait_for(layer.receive(reply_channel), remaining)
        except asyncio.TimeoutError:
            break
        tabs[reply["channel_name"]] = BrowserTab(
            tab_id=reply["tab_id"], channel_name=reply["channel_name"], page=reply["page"],
        )
    return list(tabs.values())


async def navigate_browser_tab(tab: BrowserTab, url: str, timeout: float = 3.0) -> dict[str, Any]:
    """Send navigation to one discovered connection and await its acknowledgement."""
    layer = get_channel_layer()
    if layer is None:
        raise RuntimeError("No channel layer is configured")
    command_id = str(uuid4())
    reply_channel = await layer.new_channel("agent.result.")
    await layer.send(tab.channel_name, {
        "type": "agent.command",
        "reply_channel": reply_channel,
        "payload": {
            "type": "command", "command_id": command_id,
            "page_id": tab.page["page_id"], "action": "navigate",
            "arguments": {"url": url},
        },
    })
    try:
        reply = await asyncio.wait_for(layer.receive(reply_channel), timeout)
        status, result = reply["status"], reply["result"]
    except asyncio.TimeoutError:
        status, result = "dispatched", {"message": "Browser acknowledgement timed out"}
    return {
        "success": status != "failed", "status": status, "result": result,
        "tab_id": tab.tab_id, "command_id": command_id, "url": url,
    }


async def navigate_browser_tabs(
    tabs: list[BrowserTab], url: str, timeout: float = 3.0,
) -> list[dict[str, Any]]:
    """Navigate each connection concurrently and preserve individual delivery failures."""
    replies = await asyncio.gather(
        *(navigate_browser_tab(tab, url, timeout) for tab in tabs), return_exceptions=True,
    )
    results: list[dict[str, Any]] = []
    for tab, reply in zip(tabs, replies):
        if isinstance(reply, BaseException):
            logger.error("Browser command delivery failed for tab %s: %s", tab.tab_id, reply)
            results.append({
                "success": False, "status": "failed", "url": url, "tab_id": tab.tab_id,
                "command_id": None, "result": {"message": "Could not deliver browser command"},
            })
        else:
            results.append(reply)
    return results
