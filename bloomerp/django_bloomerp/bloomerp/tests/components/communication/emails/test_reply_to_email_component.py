from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from bloomerp.communication.emails.actions import _resolve_email_access, delete_email
from bloomerp.communication.inbox_folder_definition import InboxFolderType
from bloomerp.components.communication.execute_inbox_action import _get_item_action
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.tests.base import (
    BaseBloomerpTestCaseWithModels,
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class EmailReplyFixtureMixin:
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="email-reply-owner",
            email="owner@example.com",
            password="password",
        )
        self.inbox = Inbox.objects.create(user=self.user, name="Email inbox")
        self.email_account = EmailAccount.objects.create(
            name="Support",
            email_address="support@example.com",
        )
        self.folder = InboxFolder.objects.create(
            inbox=self.inbox,
            type=InboxFolderType.EMAIL.value.key,
            related_object_id=str(self.email_account.pk),
        )
        self.item = InboxItem.objects.create(
            folder=self.folder,
            item_type=InboxFolderType.EMAIL.value.item_type.key,
            related_item_id="<original@example.com>",
            actor="Alice Example <alice@example.com>",
            datetime_received=timezone.now(),
            title="Quarterly report",
            raw_meta_data={
                "email_account_id": str(self.email_account.pk),
                "message_id": "<original@example.com>",
                "references": ["<root@example.com>"],
                "to": ["support@example.com"],
                "attachments": [
                    {
                        "id": "original-attachment",
                        "filename": "original.pdf",
                        "content_type": "application/pdf",
                        "size": 100,
                    }
                ],
            },
        )
        self.sent_item = InboxItem.objects.create(
            folder=self.folder,
            item_type=InboxFolderType.EMAIL.value.item_type.key,
            related_item_id="<sent@example.com>",
            actor=self.email_account.email_address,
            is_read=True,
            datetime_received=timezone.now(),
            title="Re: Quarterly report",
            raw_meta_data={
                "provider": "smtp",
                "message_id": "<sent@example.com>",
                "email_account_id": str(self.email_account.pk),
                "to": ["alice@example.com"],
                "outbound_body_html": "<p>Sent body</p>",
            },
        )


class TestReplyToEmailComponent(EmailReplyFixtureMixin, BloomerpComponentTestCase):
    """Tests rendering and submitting the email reply component."""

    view_name = "components_reply_to_email"

    def get_test_scenarios(self) -> list[RequestScenario]:
        return [
            RequestScenario(
                name="render sanitized quoted email",
                user=self.user,
                query_params={"item_id": self.item.pk},
                prepare=self._prepare_unsafe_original,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text('value="alice@example.com"'),
                        self.contains_text('value="Re: Quarterly report"'),
                        self.contains_text("Alice Example &lt;alice@example.com&gt;"),
                        self.contains_text("<strong>Original body</strong>"),
                        self.contains_text('style="color: red;"'),
                        self.contains_text("data-email-quoted-content"),
                        self.contains_text('contenteditable="false"'),
                        self.does_not_contain_text("<script"),
                        self.does_not_contain_text("onerror"),
                        self.does_not_contain_text("javascript:"),
                        self.does_not_contain_text("original.pdf"),
                        self.contains_text("Send reply"),
                    ],
                ),
            ),
            RequestScenario(
                name="prefer Reply-To address",
                user=self.user,
                query_params={"item_id": self.item.pk},
                prepare=self._prepare_reply_to,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text('value="replies@example.com"'),
                        self.does_not_contain_text('value="alice@example.com"'),
                    ],
                ),
            ),
            RequestScenario(
                name="fall back from invalid Reply-To address",
                user=self.user,
                query_params={"item_id": self.item.pk},
                prepare=self._prepare_invalid_reply_to,
                expected=ExpectedResult(
                    response_validators=self.contains_text(
                        'value="alice@example.com"'
                    ),
                ),
            ),
            RequestScenario(
                name="send threaded reply",
                method="POST",
                user=self.user,
                data={
                    "reply_to_item_id": self.item.pk,
                    "to": "alice@example.com",
                    "cc": "manager@example.com",
                    "bcc": "",
                    "subject": "Re: Quarterly report",
                    "body": "<p>Thanks, Alice.</p>",
                    "attachments": SimpleUploadedFile(
                        "manual.txt",
                        b"manual attachment",
                        content_type="text/plain",
                    ),
                },
                prepare=self._prepare_send,
                expected=ExpectedResult(
                    response_validators=self._reply_was_sent_and_stored,
                ),
            ),
            RequestScenario(
                name="reject item without valid recipient",
                user=self.user,
                query_params={"item_id": self.item.pk},
                prepare=self._prepare_invalid_recipient,
                expected=ExpectedResult(
                    response_validators=self.contains_text(
                        "does not have a valid reply recipient"
                    ),
                ),
            ),
            RequestScenario(
                name="reply to original recipient of local sent email",
                user=self.user,
                query_params={"item_id": self.sent_item.pk},
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text('value="alice@example.com"'),
                        self.does_not_contain_text(
                            f'value="{self.email_account.email_address}"'
                        ),
                    ],
                ),
            ),
            RequestScenario(
                name="preserve existing reply subject prefix",
                user=self.user,
                query_params={"item_id": self.item.pk},
                prepare=self._prepare_prefixed_subject,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text('value="rE: Quarterly report"'),
                        self.does_not_contain_text("Re: rE:"),
                    ],
                ),
            ),
        ]

    def _patch_content(self, content="<p>Original body</p>") -> None:
        content_patch = patch(
            "bloomerp.components.communication.emails.reply_to_email."
            "fetch_email_content",
            return_value=content,
        )
        content_patch.start()
        self.addCleanup(content_patch.stop)

    def _prepare_unsafe_original(self, _setup: RequestScenario) -> None:
        self._patch_content(
            '<p style="color: red"><strong>Original body</strong>'
            '<img src="https://example.com/pixel.png" onerror="alert(1)">'
            '<script>alert(2)</script><a href="javascript:alert(3)">link</a></p>'
        )

    def _prepare_reply_to(self, _setup: RequestScenario) -> None:
        self._patch_content()
        self.item.refresh_from_db()
        self.item.raw_meta_data["reply_to"] = ["replies@example.com"]
        self.item.save(update_fields=["raw_meta_data"])

    def _prepare_invalid_reply_to(self, _setup: RequestScenario) -> None:
        self._patch_content()
        self.item.refresh_from_db()
        self.item.raw_meta_data["reply_to"] = ["not-an-email"]
        self.item.save(update_fields=["raw_meta_data"])

    def _prepare_send(self, _setup: RequestScenario) -> None:
        self._patch_content("<p><strong>Original body</strong></p>")
        adapter_patch = patch(
            "bloomerp.components.communication.emails.reply_to_email."
            "_resolve_email_adapter_for_account"
        )
        self.adapter = adapter_patch.start().return_value
        self.adapter.send_email.return_value = "<reply@example.com>"
        self.addCleanup(adapter_patch.stop)

    def _prepare_invalid_recipient(self, _setup: RequestScenario) -> None:
        self.item.refresh_from_db()
        self.item.actor = "Undeliverable sender"
        self.item.save(update_fields=["actor"])

    def _prepare_prefixed_subject(self, _setup: RequestScenario) -> None:
        self._patch_content()
        self.item.refresh_from_db()
        self.item.title = "rE: Quarterly report"
        self.item.save(update_fields=["title"])

    def _reply_was_sent_and_stored(self, _response) -> bool:
        send_kwargs = self.adapter.send_email.call_args.kwargs
        sent_item = InboxItem.objects.get(related_item_id="<reply@example.com>")
        original = InboxItem.objects.get(pk=self.item.pk)
        return all(
            (
                send_kwargs["to"] == ["alice@example.com"],
                send_kwargs["cc"] == ["manager@example.com"],
                send_kwargs["in_reply_to"] == "<original@example.com>",
                send_kwargs["references"]
                == ["<root@example.com>", "<original@example.com>"],
                "Thanks, Alice." in send_kwargs["body_html"],
                "Original body" in send_kwargs["body_html"],
                [item.filename for item in send_kwargs["attachments"]]
                == ["manual.txt"],
                sent_item.raw_meta_data["conversation_id"]
                == original.raw_meta_data["conversation_id"],
                sent_item.raw_meta_data["parent_item_id"] == str(original.pk),
            )
        )


class TestEmailReplyActions(EmailReplyFixtureMixin, BaseBloomerpTestCaseWithModels):
    """Tests non-HTTP action rules for replyable and local sent messages."""

    def test_reply_action_requires_valid_recipient(self):
        self.item.actor = "Undeliverable sender"
        self.item.save(update_fields=["actor"])

        with self.assertRaises(ValidationError):
            _get_item_action(self.item, "reply_to_email")

    def test_local_sent_reply_actions_and_deletion(self):
        self.assertEqual(
            _get_item_action(self.sent_item, "reply_to_email").key,
            "reply_to_email",
        )
        with self.assertRaises(ValidationError):
            _get_item_action(self.sent_item, "mark_as_read")
        with self.assertRaisesMessage(
            ValidationError,
            "not connected to a synchronized provider message",
        ):
            _resolve_email_access(self.sent_item)

        delete_email(self.sent_item, Mock())

        self.assertFalse(InboxItem.objects.filter(pk=self.sent_item.pk).exists())
