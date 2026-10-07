"""Pure schema and refresh contracts for mailbox configuration."""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from bloomerp.communication.builtins.emails.mailboxes import (
    default_mailbox_mapping,
    merge_mailboxes,
    normalize_mailboxes,
)


class TestMailboxMapping(SimpleTestCase):
    def test_refresh_preserves_user_configuration(self) -> None:
        """Use case: Provider discovery runs again. Expected result: Custom settings survive."""
        # 1. Configure labels, roles and a color.
        mapping = default_mailbox_mapping(["INBOX", "Sent"])
        mapping["INBOX"].update(
            label="Customer mail", color="#123456", main_folder=False
        )
        mapping["Sent"]["main_folder"] = True
        # 2. Add a discovered folder without resetting existing settings.
        merged = merge_mailboxes(["INBOX", "Sent", "Archive"], mapping)
        self.assertEqual(merged["INBOX"], mapping["INBOX"])
        self.assertEqual(merged["Sent"], mapping["Sent"])
        self.assertFalse(merged["Archive"]["main_folder"])

    def test_ambiguous_roles_and_css_are_rejected(self) -> None:
        """Use case: An invalid mapping is supplied. Expected result: Validation fails safely."""
        # 1. Start from valid discovered mailboxes.
        mapping = default_mailbox_mapping(["INBOX", "Sent"])
        # 2. Reject multiple default inboxes and non-color CSS.
        mapping["Sent"]["main_folder"] = True
        with self.assertRaises(ValidationError):
            normalize_mailboxes(mapping)
        mapping["Sent"]["main_folder"] = False
        mapping["INBOX"]["color"] = "red;display:none"
        with self.assertRaises(ValidationError):
            normalize_mailboxes(mapping)

    def test_configured_sent_folder_overrides_discovery(self) -> None:
        """Use case: A custom Sent role is configured. Expected result: IMAP uses that folder."""
        from unittest.mock import patch
        from bloomerp.communication.builtins.emails.providers.imap_smtp import ImapSmtpAdapter
        from bloomerp.models.communication.email_account import EmailAccount

        # 1. Configure a Sent folder whose name is not a provider convention.
        account = EmailAccount(
            mailboxes={"Outgoing archive": {"label": "Sent", "sent_folder": True}}
        )
        adapter = ImapSmtpAdapter(account)
        # 2. Resolve its role without listing or creating server mailboxes.
        with patch.object(adapter, "connect") as connect:
            self.assertEqual(adapter._sent_mailbox(), "Outgoing archive")
            connect.assert_not_called()
