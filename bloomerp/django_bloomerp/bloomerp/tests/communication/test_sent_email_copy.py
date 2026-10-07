import imaplib
import smtplib
from email import message_from_bytes
from email.policy import SMTP, default
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from bloomerp.communication.builtins.emails.base_adapter import EmailAttachment
from bloomerp.communication.builtins.emails.providers.imap_smtp import (
    SENT_COPY_TIMEOUT_SECONDS,
    ImapSmtpAdapter,
)
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.views.communication.create_email_account import EmailAccountSettingsForm


class SentEmailCopyTests(SimpleTestCase):
    def setUp(self) -> None:
        """Prepare an unsaved account and fake SMTP/IMAP servers for send contracts."""
        self.account = EmailAccount(
            email_address="sender@example.com",
            smtp_host="smtp.example.com",
            smtp_port=587,
            imap_host="imap.example.com",
            imap_port=993,
            save_sent_emails=True,
        )
        self.adapter = ImapSmtpAdapter(self.account)
        self.smtp = MagicMock()
        self.smtp.__enter__.return_value = self.smtp
        self.imap = MagicMock()
        self.imap.list.return_value = ("OK", [rb'(\Sent) "/" "Sent Items"'])
        self.imap.append.return_value = ("OK", [b"Saved"])
        self.smtp_patch = patch.object(
            self.adapter, "_connect_smtp", return_value=self.smtp
        )
        self.imap_patch = patch(
            "bloomerp.communication.builtins.emails.providers.imap_smtp.imaplib.IMAP4_SSL",
            return_value=self.imap,
        )
        self.smtp_patch.start()
        self.imap_constructor = self.imap_patch.start()
        self.addCleanup(self.smtp_patch.stop)
        self.addCleanup(self.imap_patch.stop)

    def send_message(self) -> str:
        """Send a multipart message with threading headers and an attachment."""
        return self.adapter.send_email(
            to=["recipient@example.com"],
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
            subject="Proposal",
            body_text="Please review.",
            body_html="<p>Please review.</p>",
            attachments=[
                EmailAttachment(
                    filename="proposal.pdf",
                    content=b"proposal",
                    content_type="application/pdf",
                )
            ],
            in_reply_to="<parent@example.com>",
            references=["<parent@example.com>"],
        )

    def test_enabled_saves_the_complete_sent_message(self) -> None:
        """Use case: Save an outgoing message. Expected result: A read MIME copy follows SMTP."""
        # 1. Capture the operation order across both servers.
        operations = MagicMock()
        operations.attach_mock(self.smtp.send_message, "send")
        operations.attach_mock(self.imap.append, "append")
        # 2. Send and inspect the saved copy.
        message_id = self.send_message()
        mailbox, flags, _, content = self.imap.append.call_args.args
        saved = message_from_bytes(content, policy=default)
        # 3. Verify the complete MIME content and a single successful send.
        self.assertEqual(mailbox, '"Sent Items"')
        self.assertEqual(flags, r"(\Seen)")
        self.assertEqual(saved["Message-ID"], message_id)
        self.assertEqual(saved["Subject"], "Proposal")
        self.assertEqual(saved["To"], "recipient@example.com")
        self.assertEqual(saved["Cc"], "cc@example.com")
        self.assertIsNone(saved["Bcc"])
        self.assertEqual(saved["In-Reply-To"], "<parent@example.com>")
        self.assertEqual(saved["References"], "<parent@example.com>")
        self.assertEqual(
            saved.get_body(preferencelist=("html",)).get_content().strip(),
            "<p>Please review.</p>",
        )
        self.assertEqual(
            next(saved.iter_attachments()).get_payload(decode=True), b"proposal"
        )
        self.assertEqual(
            content, self.smtp.send_message.call_args.args[0].as_bytes(policy=SMTP)
        )
        self.assertEqual(
            [call[0] for call in operations.mock_calls], ["send", "append"]
        )
        self.smtp.send_message.assert_called_once()
        self.imap.logout.assert_called_once()

    def test_disabled_does_not_connect_to_imap(self) -> None:
        """Use case: Provider saves automatically. Expected result: No extra Sent copy."""
        # 1. Keep the opt-in setting disabled.
        self.account.save_sent_emails = False
        # 2. Send successfully without accessing the incoming server.
        self.send_message()
        self.imap_constructor.assert_not_called()
        self.imap.append.assert_not_called()

    def test_smtp_failure_does_not_save_a_copy(self) -> None:
        """Use case: SMTP rejects the send. Expected result: An error and no Sent copy."""
        # 1. Simulate a rejected SMTP message.
        self.smtp.send_message.side_effect = smtplib.SMTPException("Rejected")
        # 2. Verify that saving is skipped after the failed send.
        with self.assertRaises(ValidationError):
            self.send_message()
        self.imap.append.assert_not_called()

    def test_copy_failures_preserve_successful_send(self) -> None:
        """Use case: IMAP saving fails. Expected result: A warning and no SMTP retry."""
        # 1. Cover server rejection, protocol failure, and network failure.
        for failure in (None, imaplib.IMAP4.error("Failed"), OSError("Offline")):
            with self.subTest(failure=failure):
                self.smtp.send_message.reset_mock()
                self.imap.append.return_value = ("NO", [b"Rejected"])
                self.imap.append.side_effect = failure
                # 2. Preserve the successful SMTP result and report the copy failure.
                with self.assertLogs(
                    "bloomerp.communication.builtins.emails.providers.imap_smtp", level="WARNING"
                ) as logs:
                    message_id = self.send_message()
                self.assertTrue(message_id.startswith("<"))
                self.assertIn(
                    "was sent, but its copy could not be saved", logs.output[0]
                )
                self.smtp.send_message.assert_called_once()

    def test_imap_connection_failure_preserves_successful_send(self) -> None:
        """Use case: IMAP is unavailable. Expected result: Log a copy failure without resending."""
        # 1. Make the copy's IMAP connection fail after SMTP has accepted the message.
        self.imap_constructor.side_effect = OSError("Offline")
        # 2. Report the copy failure while retaining the successful send result.
        with self.assertLogs(
            "bloomerp.communication.builtins.emails.providers.imap_smtp", level="WARNING"
        ):
            message_id = self.send_message()
        self.assertTrue(message_id.startswith("<"))
        self.smtp.send_message.assert_called_once()
        self.imap.append.assert_not_called()

    def test_copy_connection_is_bounded_in_all_security_modes(self) -> None:
        """Use case: Save over SSL, STARTTLS, or plain IMAP. Expected result: Bounded socket waits."""
        # 1. Exercise every supported security mode with fake connections.
        with patch(
            "bloomerp.communication.builtins.emails.providers.imap_smtp.imaplib.IMAP4",
            return_value=self.imap,
        ) as plain_constructor:
            for security in ("ssl_tls", "starttls", "none"):
                with self.subTest(security=security):
                    self.account.imap_security = security
                    self.imap_constructor.reset_mock()
                    plain_constructor.reset_mock()
                    self.imap.starttls.reset_mock()
                    # 2. Verify the copy's socket timeout and STARTTLS negotiation.
                    self.send_message()
                    constructor = (
                        self.imap_constructor
                        if security == "ssl_tls"
                        else plain_constructor
                    )
                    constructor.assert_called_once_with(
                        "imap.example.com",
                        993,
                        timeout=SENT_COPY_TIMEOUT_SECONDS,
                    )
                    if security == "starttls":
                        self.imap.starttls.assert_called_once_with()
                    else:
                        self.imap.starttls.assert_not_called()

    def test_stalled_copy_operations_do_not_turn_success_into_send_failure(
        self,
    ) -> None:
        """Use case: IMAP stalls after sending. Expected result: Warn and return SMTP success."""
        # 1. Cover the greeting, authentication, discovery, saving, and cleanup.
        for operation in (
            self.imap_constructor,
            self.imap.login,
            self.imap.list,
            self.imap.append,
            self.imap.close,
            self.imap.logout,
        ):
            with self.subTest(operation=operation):
                operation.side_effect = TimeoutError("IMAP operation timed out")
                self.smtp.send_message.reset_mock()
                try:
                    # 2. Preserve the accepted SMTP send and emit a copy warning.
                    with self.assertLogs(
                        "bloomerp.communication.builtins.emails.providers.imap_smtp",
                        level="WARNING",
                    ):
                        message_id = self.send_message()
                    self.assertTrue(message_id.startswith("<"))
                    self.smtp.send_message.assert_called_once()
                finally:
                    operation.side_effect = None

    def test_neo_sent_folder_without_special_use_flag(self) -> None:
        """Use case: Neo lists a plain Sent folder. Expected result: Save in that folder."""
        # 1. Supply a conventional folder without special-use metadata.
        self.imap.list.return_value = ("OK", [b'() "/" "INBOX"', b'() "/" "Sent"'])
        # 2. Verify the folder used by APPEND.
        self.send_message()
        self.assertEqual(self.imap.append.call_args.args[0], '"Sent"')

    def test_missing_sent_folder_does_not_append_elsewhere(self) -> None:
        """Use case: No selectable Sent folder exists. Expected result: Warn without a resend."""
        # 1. A nonselectable Sent folder cannot hold the message.
        self.imap.list.return_value = (
            "OK",
            [rb'(\Noselect \Sent) "/" "Sent"', b'() "/" "INBOX"'],
        )
        # 2. Do not create an arbitrary folder or store the email in INBOX.
        with self.assertLogs(
            "bloomerp.communication.builtins.emails.providers.imap_smtp", level="WARNING"
        ):
            self.send_message()
        self.imap.append.assert_not_called()
        self.smtp.send_message.assert_called_once()

    def test_setting_is_available_in_account_setup_and_detail_layout(self) -> None:
        """Use case: Configure Sent saving. Expected result: Setup and detail expose the checkbox."""
        # 1. Build the provider-filtered account form and configured detail layout.
        form = EmailAccountSettingsForm(provider="imap")
        layouts = EmailAccount.bloomerp_config.detail_view_settings.layouts
        # 2. Verify the setting is editable and disabled by default.
        self.assertIn("save_sent_emails", form.fields)
        self.assertFalse(form.fields["save_sent_emails"].initial)
        self.assertEqual(
            form.fields["save_sent_emails"].widget.attrs["class"],
            "checkbox checkbox-primary",
        )
        self.assertIn(
            "save_sent_emails",
            [
                item.id
                for layout in layouts
                for row in layout.rows
                for item in row.items
            ],
        )
