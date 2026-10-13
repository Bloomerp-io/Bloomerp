from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from bloomerp.communication.builtins.emails.providers.imap_smtp import ImapSmtpAdapter


class ImapEmailThreadMetadataTests(SimpleTestCase):
    def test_synced_email_contains_threading_headers(self):
        message = EmailMessage()
        message["Message-ID"] = "<current@example.com>"
        message["In-Reply-To"] = "<parent@example.com>"
        message["References"] = "<root@example.com> <parent@example.com>"
        message["Reply-To"] = "Support Team <replies@example.com>"
        message.set_content("Threaded email")
        adapter = ImapSmtpAdapter(SimpleNamespace(pk="account-id"))
        connection = Mock()
        connection.uid.return_value = (
            "OK",
            [(br"1 (UID 42 FLAGS (\Seen) BODY[])", message.as_bytes())],
        )
        adapter.connect = Mock(return_value=connection)

        email = adapter._fetch_email_index("42", mailbox="INBOX")

        self.assertEqual(email.in_reply_to, "<parent@example.com>")
        self.assertEqual(
            email.references,
            ["<root@example.com>", "<parent@example.com>"],
        )
        self.assertEqual(
            email.retrieval_metadata()["references"],
            ["<root@example.com>", "<parent@example.com>"],
        )
        self.assertEqual(email.reply_to, ["replies@example.com"])
        self.assertEqual(
            email.retrieval_metadata()["reply_to"],
            ["replies@example.com"],
        )
