"""Exercise the dedicated conversation socket through the registered route."""

from uuid import uuid4

from bloomerp.models import User
from bloomerp.models.communication.instant_messaging import (
    IMConversation,
    IMConversationParticipant,
)
from bloomerp.router import router
from bloomerp.tests.base import (
    BloomerpChannelTestCase,
    ChannelScenario,
    Connect,
    Disconnect,
    ExpectJson,
    ExpectNoMessage,
    PublishGroupEvent,
)


class TestIMConversationSocket(BloomerpChannelTestCase):
    """Verify membership gates the socket and only matching invalidations pass."""

    def setUp(self) -> None:
        """Create a member, outsider and private native conversation."""
        super().setUp()
        self.registry = router
        self.member = User.objects.create_user(username="im-socket-member")
        self.outsider = User.objects.create_user(username="im-socket-outsider")
        self.chat = IMConversation.objects.create(kind="group")
        IMConversationParticipant.objects.create(
            conversation=self.chat, user=self.member
        )

    def get_test_scenarios(self) -> list[ChannelScenario]:
        """Use the shared channel scenario runner for delivery and denial."""
        path = f"/ws/communication/conversation/{self.chat.pk}/"
        return [
            ChannelScenario(
                name="Member receives only matching refresh",
                steps=[
                    Connect(path=path, user=self.member),
                    PublishGroupEvent(
                        group=f"user_{self.member.pk}",
                        event={
                            "type": "notify",
                            "payload": {
                                "action": "im.message.created",
                                "conversation_id": str(uuid4()),
                            },
                        },
                    ),
                    ExpectNoMessage(),
                    PublishGroupEvent(
                        group=f"user_{self.member.pk}",
                        event={
                            "type": "notify",
                            "payload": {
                                "action": "im.message.created",
                                "conversation_id": str(self.chat.pk),
                            },
                        },
                    ),
                    ExpectJson(payload={"action": "refresh"}),
                    Disconnect(),
                ],
            ),
            ChannelScenario(
                name="Outsider denied",
                steps=[
                    Connect(
                        path=path, user=self.outsider, accepted=False, close_code=4403
                    )
                ],
            ),
            ChannelScenario(
                name="Anonymous denied",
                steps=[Connect(path=path, accepted=False, close_code=4403)],
            ),
        ]
