from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from bloomerp.communication.builtins.instant_messaging.controller import IMController
from bloomerp.communication.builtins.instant_messaging.inbox_source import (
    publish_conversation_activity,
)
from bloomerp.components.communication.render_inbox_item import render_inbox_item
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.models.communication.instant_messaging import (
    IMConversation,
    IMConversationParticipant,
)
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestRenderInboxItemBehavior(SimpleTestCase):
    """Tests provider side effects that require a fully mocked inbox item."""

    def setUp(self) -> None:
        """Build an authenticated request for isolated inbox render callbacks."""
        self.request = RequestFactory().get("/inbox-item/")
        self.request.user = Mock(is_authenticated=True)

    @patch("bloomerp.components.communication.render_inbox_item.Inbox")
    @patch("bloomerp.components.communication.render_inbox_item.render")
    @patch("bloomerp.components.communication.render_inbox_item.get_object_or_404")
    @patch("bloomerp.components.communication.render_inbox_item.accessible_inbox_items")
    def test_already_read_item_does_not_repeat_provider_mark_as_read(
        self,
        accessible_inbox_items: Mock,
        get_object_or_404: Mock,
        render: Mock,
        inbox: Mock,
    ) -> None:
        """Check the registered read callback follows the stored read flag."""
        item_type = Mock(actions=[])
        item_type.on_render.return_value = "Stored sent email"
        item = Mock(is_read=True)
        item.get_inbox_item_type.return_value = item_type
        get_object_or_404.return_value = item
        render.return_value = HttpResponse()
        inbox.get_unread_count_for_user.return_value = 0

        render_inbox_item(self.request, "item-id")

        item_type.on_render.assert_called_once_with(item, self.request)
        item_type.on_mark_as_read.assert_not_called()

    @patch("bloomerp.components.communication.render_inbox_item.Inbox")
    @patch("bloomerp.components.communication.render_inbox_item.render")
    @patch("bloomerp.components.communication.render_inbox_item.get_object_or_404")
    @patch("bloomerp.components.communication.render_inbox_item.accessible_inbox_items")
    def test_unread_item_is_marked_as_read_after_rendering(
        self,
        accessible_inbox_items: Mock,
        get_object_or_404: Mock,
        render: Mock,
        inbox: Mock,
    ) -> None:
        """Check the registered read callback follows the stored read flag."""
        item_type = Mock(actions=[])
        item_type.on_render.return_value = "Received email"
        item = Mock(is_read=False)
        item.get_inbox_item_type.return_value = item_type
        get_object_or_404.return_value = item
        render.return_value = HttpResponse()
        inbox.get_unread_count_for_user.return_value = 0

        render_inbox_item(self.request, "item-id")

        item_type.on_mark_as_read.assert_called_once_with(item, self.request)


class TestIMInboxRendering(BloomerpComponentTestCase):
    """Exercise conversation delivery and rendering at the existing inbox endpoint."""

    view_name = "components_render_inbox_item"

    def prepare_conversation(self, scenario: RequestScenario) -> None:
        """Send twice and retry source delivery before opening the same conversation item."""
        inbox = Inbox.objects.create(user=self.normal_user, name="IM test")
        self.folder = InboxFolder.objects.create(inbox=inbox, type="instant_messaging")
        self.chat = IMConversation.objects.create(name="Inbox conversation")
        self.member = IMConversationParticipant.objects.create(
            conversation=self.chat, user=self.normal_user
        )
        IMConversationParticipant.objects.create(
            conversation=self.chat, user=self.admin_user
        )
        with TestCase.captureOnCommitCallbacks(execute=True):
            IMController(self.admin_user).send_message(
                self.chat.pk, "<p>First message</p>", "first"
            )
            self.latest = IMController(self.admin_user).send_message(
                self.chat.pk, "<p>Latest message</p>", "latest"
            )
        publish_conversation_activity(self.chat.pk)
        self.item = InboxItem.objects.get(
            folder=self.folder, related_item_id=str(self.chat.pk)
        )
        self.assertEqual(self.item.snippet, "Latest message")
        self.assertFalse(self.item.is_read)
        scenario.view_kwargs = {"item_id": str(self.item.pk)}

    def prepare_revoked(self, scenario: RequestScenario) -> None:
        """Revoke membership after delivery to ensure stored previews grant no access."""
        self.prepare_conversation(scenario)
        self.member.left_at = timezone.now()
        self.member.save(update_fields=["left_at"])

    def prepare_read(self, scenario: RequestScenario) -> None:
        """Acknowledge rendered messages through the controller used by both hosts."""
        self.prepare_conversation(scenario)
        IMController(self.normal_user).mark_read(self.chat.pk, self.latest.pk)
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_read)
        with TestCase.captureOnCommitCallbacks(execute=True):
            IMController(self.admin_user).send_message(
                self.chat.pk, "<p>New unread message</p>", "third"
            )
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_read)
        self.assertEqual(InboxItem.objects.filter(folder=self.folder).count(), 1)

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover fragment reuse, read synchronization, upserts and revoked access."""
        return [
            RequestScenario(
                name="Render the conversation with editor",
                user=self.normal_user,
                prepare=self.prepare_conversation,
                expected=ExpectedResult(
                    status_code=200,
                    response_validators=[
                        self.contains_text("data-conversation-id"),
                        self.contains_text("bloomerp-text-editor"),
                        self.contains_text("Latest message"),
                    ],
                ),
            ),
            RequestScenario(
                name="Read then receive updates the same item",
                user=self.normal_user,
                prepare=self.prepare_read,
                expected=ExpectedResult(
                    status_code=200,
                    response_validators=[self.contains_text("New unread message")],
                ),
            ),
            RequestScenario(
                name="Revoked participant cannot open stored item",
                user=self.normal_user,
                prepare=self.prepare_revoked,
                expected=ExpectedResult(status_code=404),
            ),
        ]
