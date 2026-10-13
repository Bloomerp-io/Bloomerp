"""Exercise conversation expansion at the permission-scoped inbox boundary."""

from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    RequestScenario,
    ExpectedResult,
)


class TestInboxConversationComponent(BloomerpComponentTestCase):
    view_name = "components_render_inbox_folder_items"

    def prepare_messages(self, scenario: RequestScenario) -> None:
        """Seed a received message, a sent reply and unrelated account/thread controls."""
        account = EmailAccount.objects.create(
            email_address="thread@example.com", mailboxes=["INBOX", "Sent"]
        )
        inbox = Inbox.objects.create(name="Thread inbox", user=self.admin_user)
        folder = InboxFolder.objects.create(
            inbox=inbox, type="email", related_object_id=str(account.pk)
        )
        InboxItem.objects.create(
            folder=folder,
            item_type="email",
            title="Received anchor",
            related_item_id="<root@example.com>",
            raw_meta_data={"mailbox": "INBOX", "message_id": "<root@example.com>"},
        )
        InboxItem.objects.create(
            folder=folder,
            item_type="email",
            title="Sent reply context",
            related_item_id="<reply@example.com>",
            raw_meta_data={
                "mailbox": "Sent",
                "message_id": "<reply@example.com>",
                "in_reply_to": "<root@example.com>",
                "references": ["<root@example.com>"],
            },
        )
        InboxItem.objects.create(
            folder=folder,
            item_type="email",
            title="Unrelated sent message",
            related_item_id="<unrelated@example.com>",
            raw_meta_data={"mailbox": "Sent"},
        )
        other = InboxFolder.objects.create(inbox=inbox, type="email")
        InboxItem.objects.create(
            folder=other,
            item_type="email",
            title="Other account secret",
            related_item_id="<root@example.com>",
        )
        scenario.view_kwargs = {"folder_id": str(folder.pk)}

    def prepare_local_relationship(self, scenario: RequestScenario) -> None:
        """Link local replies without RFC headers to the same original message."""
        self.prepare_messages(scenario)
        anchor = InboxItem.objects.get(title="Received anchor")
        reply = InboxItem.objects.get(title="Sent reply context")
        anchor.related_item_id = "legacy-local-id"
        anchor.raw_meta_data = {"mailbox": "INBOX", "conversation_id": str(anchor.pk)}
        anchor.save(update_fields=["related_item_id", "raw_meta_data"])
        reply.related_item_id = "legacy-local-reply"
        reply.raw_meta_data = {"mailbox": "Sent", "parent_item_id": str(anchor.pk)}
        reply.save(update_fields=["related_item_id", "raw_meta_data"])

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Keep main-folder filtering while including only related same-account context."""
        return [
            RequestScenario(
                name="Expand stored local reply relationships without RFC headers",
                user=self.admin_user,
                prepare=self.prepare_local_relationship,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Sent reply context"),
                        self.contains_text("1 related message"),
                    ]
                ),
            ),
            RequestScenario(
                name="Expand sent replies outside the default main mailbox",
                user=self.admin_user,
                prepare=self.prepare_messages,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Received anchor"),
                        self.contains_text("Sent reply context"),
                        self.contains_text("1 related message"),
                        self.does_not_contain_text("Unrelated sent message"),
                        self.does_not_contain_text("Other account secret"),
                    ]
                ),
            ),
        ]
