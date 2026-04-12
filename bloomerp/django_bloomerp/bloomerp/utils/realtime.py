from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def send_user_message(user_id: int, payload: dict) -> None:
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    
    async_to_sync(channel_layer.group_send)(
        f'user_{user_id}',
        {
            'type': 'notify',
            'payload': payload,
        },
    )
