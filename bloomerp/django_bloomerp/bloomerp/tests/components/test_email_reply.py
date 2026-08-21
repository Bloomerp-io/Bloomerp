from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from bloomerp.communication.emails.providers.imap_smtp import ImapSmtpAdapter
from bloomerp.communication.inbox_folder_definition import InboxFolderType
from bloomerp.components.communication.execute_inbox_action import _get_item_action
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem


class ImapEmailThreadMetadataTests(SimpleTestCase):
    def test_synced_email_contains_threading_headers(self):
        """
        Use case: An IMAP email is already part of an external email thread.
        Expected result: Its In-Reply-To and References headers are retained for later replies.
        """
        # 1. Return a MIME message containing a complete thread header chain.
        message = EmailMessage()
        message["Message-ID"] = "<current@example.com>"
        message["In-Reply-To"] = "<parent@example.com>"
        message["References"] = "<root@example.com> <parent@example.com>"
        message.set_content("Threaded email")
        adapter = ImapSmtpAdapter(SimpleNamespace(pk="account-id"))
        connection = Mock()
        connection.uid.return_value = (
            "OK",
            [(br"1 (UID 42 FLAGS (\Seen) BODY[])", message.as_bytes())],
        )
        adapter.connect = Mock(return_value=connection)

        # 2. Convert the provider message to provider-neutral metadata.
        email = adapter._fetch_email_index("42", mailbox="INBOX")

        # 3. Verify the threading headers survive synchronization metadata creation.
        self.assertEqual(email.in_reply_to, "<parent@example.com>")
        self.assertEqual(
            email.references,
            ["<root@example.com>", "<parent@example.com>"],
        )
        self.assertEqual(
            email.retrieval_metadata()["references"],
            ["<root@example.com>", "<parent@example.com>"],
        )


class EmailReplyComponentTests(TestCase):
    def setUp(self):
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
        self.client.force_login(self.user)
        self.reply_url = reverse("components_reply_to_email")

    @patch(
        "bloomerp.components.communication.emails.reply_to_email."
        "fetch_email_content"
    )
    def test_reply_composer_prefills_and_sanitizes_quoted_email(self, fetch_content):
        """
        Use case: A user opens Reply for an HTML email with unsafe markup.
        Expected result: Recipient, subject, headers, and safe formatting render above an immutable quote.
        """
        # 1. Return formatted email HTML containing executable markup.
        fetch_content.return_value = (
            '<p style="color: red"><strong>Original body</strong>'
            '<img src="https://example.com/pixel.png" onerror="alert(1)">'
            '<script>alert(2)</script><a href="javascript:alert(3)">link</a></p>'
        )

        # 2. Open the reply composer for the accessible email item.
        response = self.client.get(self.reply_url, {"item_id": self.item.pk})
        html = response.content.decode()

        # 3. Verify defaults, quoted headers, formatting, and sanitization.
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="alice@example.com"', html)
        self.assertIn('value="Re: Quarterly report"', html)
        self.assertIn("Alice Example &lt;alice@example.com&gt;", html)
        self.assertIn("support@example.com", html)
        self.assertIn("Quarterly report", html)
        self.assertIn("<strong>Original body</strong>", html)
        self.assertIn('style="color: red;"', html)
        self.assertIn("data-email-quoted-content", html)
        self.assertIn('contenteditable="false"', html)
        self.assertNotIn("<script", html)
        self.assertNotIn("onerror", html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("original.pdf", html)
        self.assertIn(f'hx-post="{self.reply_url}"', html)
        self.assertIn("Send reply", html)

    @patch(
        "bloomerp.components.communication.emails.reply_to_email."
        "_resolve_email_adapter_for_account"
    )
    @patch(
        "bloomerp.components.communication.emails.reply_to_email."
        "fetch_email_content"
    )
    def test_sending_reply_threads_and_links_the_stored_message(
        self,
        fetch_content,
        resolve_adapter,
    ):
        """
        Use case: A user sends a reply and manually adds one new attachment.
        Expected result: SMTP receives threading headers and BloomERP stores a linked reply without the original attachment.
        """
        # 1. Configure the original body and the provider's sent Message-ID.
        fetch_content.return_value = "<p><strong>Original body</strong></p>"
        adapter = Mock()
        adapter.send_email.return_value = "<reply@example.com>"
        resolve_adapter.return_value = adapter
        manual_attachment = SimpleUploadedFile(
            "manual.txt",
            b"manual attachment",
            content_type="text/plain",
        )

        # 2. Submit the reply with only the newly selected attachment.
        response = self.client.post(
            self.reply_url,
            {
                "reply_to_item_id": self.item.pk,
                "to": "alice@example.com",
                "cc": "manager@example.com",
                "bcc": "",
                "subject": "Re: Quarterly report",
                "body": "<p>Thanks, Alice.</p>",
                "attachments": manual_attachment,
            },
        )

        # 3. Verify the outgoing email preserves the external thread and quote.
        self.assertEqual(response.status_code, 200)
        send_kwargs = adapter.send_email.call_args.kwargs
        self.assertEqual(send_kwargs["to"], ["alice@example.com"])
        self.assertEqual(send_kwargs["cc"], ["manager@example.com"])
        self.assertEqual(send_kwargs["in_reply_to"], "<original@example.com>")
        self.assertEqual(
            send_kwargs["references"],
            ["<root@example.com>", "<original@example.com>"],
        )
        self.assertIn("Thanks, Alice.", send_kwargs["body_html"])
        self.assertIn("Original body", send_kwargs["body_html"])
        self.assertEqual(
            [attachment.filename for attachment in send_kwargs["attachments"]],
            ["manual.txt"],
        )
        self.assertNotIn("original.pdf", send_kwargs["body_html"])

        # 4. Verify the sent reply and original share a local conversation link.
        sent_item = InboxItem.objects.get(related_item_id="<reply@example.com>")
        self.item.refresh_from_db()
        self.assertEqual(
            sent_item.raw_meta_data["conversation_id"],
            self.item.raw_meta_data["conversation_id"],
        )
        self.assertEqual(sent_item.raw_meta_data["parent_item_id"], str(self.item.pk))
        self.assertEqual(
            sent_item.raw_meta_data["in_reply_to"],
            "<original@example.com>",
        )
        self.assertEqual(sent_item.raw_meta_data["outbound_body_html"], send_kwargs["body_html"])

    def test_reply_action_is_unavailable_without_a_valid_sender(self):
        """
        Use case: A synchronized email does not contain a valid sender address.
        Expected result: The Reply action cannot be resolved or executed for that item.
        """
        # 1. Remove the original item's usable sender address.
        self.item.actor = "Undeliverable sender"
        self.item.save(update_fields=["actor"])

        # 2. Resolve Reply through the same action lookup used by the component endpoint.
        with self.assertRaises(ValidationError):
            _get_item_action(self.item, "reply_to_email")

        # 3. Verify a direct request also refuses to open a reply composer.
        response = self.client.get(self.reply_url, {"item_id": self.item.pk})
        self.assertContains(response, "does not have a valid sender address")

    @patch(
        "bloomerp.components.communication.emails.reply_to_email."
        "fetch_email_content",
        return_value="<p>Original body</p>",
    )
    def test_reply_subject_does_not_duplicate_existing_prefix(self, _fetch_content):
        """
        Use case: The original subject already begins with Re: in mixed case.
        Expected result: Opening Reply does not add another prefix.
        """
        # 1. Save an already-prefixed subject.
        self.item.title = "rE: Quarterly report"
        self.item.save(update_fields=["title"])

        # 2. Open the reply composer.
        response = self.client.get(self.reply_url, {"item_id": self.item.pk})

        # 3. Verify the existing single prefix is retained.
        self.assertContains(response, 'value="rE: Quarterly report"')
        self.assertNotContains(response, "Re: rE:")
