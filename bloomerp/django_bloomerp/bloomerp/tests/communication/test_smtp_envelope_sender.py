"""SMTP protocol integration contracts that require mocked external servers."""
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from bloomerp.communication.emails.providers.imap_smtp import ImapSmtpAdapter
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.views.communication.create_email_account import EmailAccountSettingsForm


class SmtpEnvelopeSenderTests(SimpleTestCase):
    def setUp(self) -> None:
        """Prepare an alias account and a fake SMTP connection without network traffic."""
        self.account = EmailAccount(
            email_address="alias@example.com",
            username="primary@example.com",
            smtp_host="smtp.example.com",
            smtp_port=587,
        )
        self.adapter = ImapSmtpAdapter(self.account)
        self.smtp = MagicMock()
        self.smtp.__enter__.return_value = self.smtp
        self.patcher = patch.object(self.adapter, "_connect_smtp", return_value=self.smtp)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_alias_envelope_preserves_from_and_all_recipients(self) -> None:
        """Submit the primary envelope while preserving alias headers and all recipients."""
        self.account.smtp_envelope_sender = "primary@example.com"
        self.adapter.send_email(
            to=["recipient@example.com"], cc=["cc@example.com"], bcc=["bcc@example.com"],
            subject="Alias test", body_html="<p>Hello</p>",
        )
        message = self.smtp.send_message.call_args.args[0]
        self.assertEqual(message["From"], "alias@example.com")
        self.assertIsNone(message["Sender"])
        self.assertEqual(message["Reply-To"], "alias@example.com")
        self.assertIsNone(message["Bcc"])
        self.smtp.send_message.assert_called_once_with(
            message, from_addr="primary@example.com",
            to_addrs=["recipient@example.com", "cc@example.com", "bcc@example.com"],
        )

    def test_blank_envelope_does_not_infer_sender_from_login(self) -> None:
        """Keep the original envelope when no override is set despite a different login."""
        self.adapter.send_email(to=["recipient@example.com"], subject="Default", body_html="")
        self.assertEqual(self.smtp.send_message.call_args.kwargs["from_addr"], "alias@example.com")
        self.assertIsNone(self.smtp.send_message.call_args.args[0]["Reply-To"])

    def test_explicit_reply_address_is_preserved(self) -> None:
        """Preserve explicit reply routing when sending with an envelope override."""
        self.account.smtp_envelope_sender = "primary@example.com"
        self.adapter.send_email(
            to=["recipient@example.com"], subject="Reply", body_html="",
            reply_to="replies@example.com",
        )
        message = self.smtp.send_message.call_args.args[0]
        self.assertEqual(message["Reply-To"], "replies@example.com")
        self.assertEqual(message["From"], "alias@example.com")

    def test_envelope_field_is_optional_validated_and_visible(self) -> None:
        """Expose an optional email-validated envelope field in setup and account layouts."""
        form = EmailAccountSettingsForm(provider="imap")
        field = form.fields["smtp_envelope_sender"]
        self.assertFalse(field.required)
        self.assertEqual(field.clean(""), "")
        self.assertEqual(field.clean("primary@example.com"), "primary@example.com")
        with self.assertRaises(ValidationError):
            field.clean("not-an-email")
        layouts = EmailAccount.bloomerp_config.detail_view_settings.layouts
        self.assertIn("smtp_envelope_sender", [item.id for layout in layouts for row in layout.rows for item in row.items])
