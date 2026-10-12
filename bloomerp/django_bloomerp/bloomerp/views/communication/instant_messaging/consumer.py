"""Websocket invalidation view for an authorized open conversation."""

from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from bloomerp.communication.builtins.instant_messaging.access import IMAccessManager
from bloomerp.router import router


@router.register(
    re_path=r"^ws/communication/conversation/(?P<conversation_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/$",
    route_type="websocket",
)
class IMConversationConsumer(AsyncJsonWebsocketConsumer):
    """Signal new messages while keeping content behind the scoped HTTP endpoint."""

    group_name: str | None = None

    @database_sync_to_async
    def can_read(self) -> bool:
        """Recheck current membership, including after a socket was accepted."""
        return (
            IMAccessManager(self.scope["user"])
            .get_conversations()
            .filter(pk=self.scope["url_route"]["kwargs"]["conversation_id"])
            .exists()
        )

    async def connect(self) -> None:
        """Join only the authenticated user's notifications after checking membership."""
        if (
            not self.scope.get("user")
            or not self.scope["user"].is_authenticated
            or not await self.can_read()
        ):
            await self.close(code=4403)
            return
        self.group_name = f"user_{self.scope['user'].pk}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code: int) -> None:
        """Drop the subscription when the reusable conversation view closes."""
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notify(self, event: dict[str, Any]) -> None:
        """Forward only matching invalidations while the user remains authorized."""
        payload = event.get("payload", {})
        if (
            payload.get("action")
            not in ("im.message.created", "im.reactions.updated", "im.group.updated")
            or payload.get("conversation_id")
            != self.scope["url_route"]["kwargs"]["conversation_id"]
        ):
            return
        if not await self.can_read():
            await self.close(code=4403)
            return
        if payload.get("action") == "im.group.updated":
            await self.send_json(
                {"action": "group-updated", "name": await self.conversation_name()}
            )
        else:
            await self.send_json({"action": "refresh"})

    @database_sync_to_async
    def conversation_name(self) -> str:
        """Resolve current group metadata through the same membership scope."""
        return (
            IMAccessManager(self.scope["user"])
            .get_conversations()
            .filter(pk=self.scope["url_route"]["kwargs"]["conversation_id"])
            .values_list("name", flat=True)
            .first()
            or ""
        )
