from channels.generic.websocket import AsyncJsonWebsocketConsumer


class NotificationsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self) -> None:
        user = self.scope.get('user')
        if user and user.is_authenticated:
            self.group_name = f'user_{user.id}'
        else:
            self.group_name = 'anonymous'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code: int) -> None:
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content: dict, **kwargs) -> None:
        await self.send_json({'type': 'echo', 'payload': content})

    async def notify(self, event: dict) -> None:
        await self.send_json(event.get('payload', {}))
