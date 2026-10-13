from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from bloomerp.communication.builtins.emails.providers.imap_smtp import ImapSmtpAdapter


class ImapEmailAttachmentTests(SimpleTestCase):
    def setUp(self):
        self.adapter = ImapSmtpAdapter(SimpleNamespace())
        self.connection = Mock()
        self.connection.select.return_value = ("OK", [b"1"])
        self.adapter.connect = Mock(return_value=self.connection)

    def _message_bytes(self) -> bytes:
        message = EmailMessage()
        message["Subject"] = "Contract"
        message.set_content("Please review the contract.")
        message.add_alternative("<p>Please review the contract.</p>", subtype="html")
        message.add_attachment(
            b"contract content",
            maintype="application",
            subtype="pdf",
            filename="contract.pdf",
        )
        return message.as_bytes()

    def test_synced_email_contains_attachment_metadata(self):
        self.connection.uid.return_value = (
            "OK",
            [(br"1 (UID 42 FLAGS (\Seen) BODY[])", self._message_bytes())],
        )
        self.adapter.email_account = SimpleNamespace(pk="account-id")

        email = self.adapter._fetch_email_index("42", mailbox="INBOX")

        self.assertIsNotNone(email)
        self.assertEqual(len(email.attachments), 1)
        self.assertEqual(email.attachments[0].id, "2")
        self.assertEqual(email.attachments[0].filename, "contract.pdf")
        self.assertEqual(email.attachments[0].content_type, "application/pdf")
        self.assertEqual(email.attachments[0].size, len(b"contract content"))
        self.assertEqual(
            email.retrieval_metadata()["attachments"],
            [
                {
                    "id": "2",
                    "filename": "contract.pdf",
                    "content_type": "application/pdf",
                    "size": len(b"contract content"),
                }
            ],
        )

    def test_fetch_email_attachment_resolves_the_referenced_mime_part(self):
        self.connection.uid.return_value = (
            "OK",
            [(b"1 (BODY[])", self._message_bytes())],
        )

        attachment = self.adapter.fetch_email_attachment(
            "42",
            "2",
            mailbox="INBOX",
        )

        self.assertIsNotNone(attachment)
        self.assertEqual(attachment.filename, "contract.pdf")
        self.assertEqual(attachment.content_type, "application/pdf")
        self.assertEqual(attachment.content, b"contract content")
