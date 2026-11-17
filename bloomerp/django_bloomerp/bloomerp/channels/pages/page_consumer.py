"""Authorized live page invalidations; persistence stays on the generated API."""

from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from bloomerp.models import Page
from bloomerp.router import router


@router.register(path="ws/pages/<uuid:page_id>/", route_type="websocket")
class PageConsumer(AsyncJsonWebsocketConsumer):
    """Tell an open editor to reread a changed page while rechecking shared access."""

    group_name: str | None = None

    @database_sync_to_async
    def can_read(self) -> bool:
        """Recheck ownership or current group/user sharing before every notification."""
        return (
            Page.accessible_to(self.scope["user"])
            .filter(pk=self.scope["url_route"]["kwargs"]["page_id"])
            .exists()
        )

    async def connect(self) -> None:
        """Join this page's channel only for an authorized same-origin session."""
        headers = dict(self.scope.get("headers", []))
        origin = urlsplit(headers.get(b"origin", b"").decode("latin1")).netloc
        if (
            not origin
            or origin != headers.get(b"host", b"").decode("latin1")
            or not await self.can_read()
        ):
            await self.close(code=4403)
            return
        identifier = UUID(str(self.scope["url_route"]["kwargs"]["page_id"]))
        self.group_name = f"page.{identifier.hex}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code: int) -> None:
        """Remove the page subscription when either editor surface closes."""
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def page_changed(self, event: dict[str, Any]) -> None:
        """Send only revision metadata, closing sockets whose access was revoked."""
        if not await self.can_read():
            await self.close(code=4403)
            return
        await self.send_json({"version": event["version"]})
