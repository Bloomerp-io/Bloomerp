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
        from bloomerp.communication.builtins.emails.providers.imap_smtp import (
            ImapSmtpAdapter,
        )
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

    def test_sent_defaults_only_match_recognized_mailboxes(self) -> None:
        """Avoid false Sent roles while supporting conventional provider mailbox names."""
        for sent_name in (
            None,
            "Sent",
            "Sent Items",
            "Sent Mail",
            "[Gmail]/Sent Mail",
            "[Google Mail]/Sent Mail",
        ):
            with self.subTest(sent_name=sent_name):
                names = ["Unsent Messages", "Sentinel", "Recently sent reports"]
                if sent_name:
                    names.append(sent_name)
                mapping = default_mailbox_mapping(names)
                selected = [
                    name
                    for name, settings in mapping.items()
                    if settings["sent_folder"]
                ]
                self.assertEqual(selected, [sent_name] if sent_name else [])

    def test_refresh_restores_roles_when_old_mailboxes_disappear(self) -> None:
        """Restore main and Sent defaults while preserving the replacement folder's presentation."""
        previous = default_mailbox_mapping(["Old inbox", "Sent Items", "INBOX", "Sent"])
        previous["Old inbox"]["main_folder"] = True
        previous["INBOX"].update(
            main_folder=False, label="Customer mail", color="#123456"
        )
        previous["Sent Items"]["sent_folder"] = True
        previous["Sent"].update(sent_folder=False, label="Outgoing mail")
        for names in (["INBOX", "Sent"], ["INBOX", "Sent Mail"]):
            with self.subTest(names=names):
                merged = merge_mailboxes(names, previous)
                self.assertTrue(merged["INBOX"]["main_folder"])
                self.assertEqual(merged["INBOX"]["label"], "Customer mail")
                self.assertEqual(merged["INBOX"]["color"], "#123456")
                self.assertTrue(merged[names[1]]["sent_folder"])
                if "Sent" in merged:
                    self.assertEqual(merged["Sent"]["label"], "Outgoing mail")
                normalize_mailboxes(merged)

    def test_refresh_keeps_surviving_custom_roles_and_explicitly_cleared_roles(
        self,
    ) -> None:
        """Keep a surviving custom role without assigning duplicates or undoing explicit clearing."""
        previous = normalize_mailboxes(
            {
                "Custom mailbox": {
                    "label": "Custom",
                    "main_folder": True,
                    "sent_folder": True,
                },
            }
        )
        merged = merge_mailboxes(["Custom mailbox", "INBOX", "Sent"], previous)
        self.assertTrue(merged["Custom mailbox"]["main_folder"])
        self.assertTrue(merged["Custom mailbox"]["sent_folder"])
        self.assertFalse(merged["INBOX"]["main_folder"])
        self.assertFalse(merged["Sent"]["sent_folder"])
        normalize_mailboxes(merged)
        cleared = default_mailbox_mapping(["INBOX", "Sent"])
        cleared["INBOX"]["main_folder"] = False
        cleared["Sent"]["sent_folder"] = False
        self.assertEqual(merge_mailboxes(["INBOX", "Sent"], cleared), cleared)
