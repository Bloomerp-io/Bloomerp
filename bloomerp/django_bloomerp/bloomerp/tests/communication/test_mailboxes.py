"""Pure schema and refresh contracts for mailbox configuration."""

from typing import Any

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

    def test_provider_defaults_preserve_custom_and_explicitly_cleared_roles(self) -> None:
        """Use stable-ID presentation defaults without restoring roles the user cleared."""
        discovered = normalize_mailboxes({
            "main-id": {"label": "Inbox", "main_folder": True},
            "sent-id": {"label": "Sent", "sent_folder": True},
            "custom-id": {"label": "Custom"},
            "new-id": {"label": "New archive"},
        })
        previous = {name: dict(settings) for name, settings in discovered.items() if name != "new-id"}
        previous["sent-id"]["sent_folder"] = False
        previous["custom-id"].update(sent_folder=True, label="My sent mail", color="#123456")
        merged = merge_mailboxes(list(discovered), previous, provider_defaults=discovered)
        self.assertEqual(merged["custom-id"], previous["custom-id"])
        self.assertFalse(merged["sent-id"]["sent_folder"])
        self.assertEqual(merged["new-id"]["label"], "New archive")
        normalize_mailboxes(merged)
        previous["custom-id"]["sent_folder"] = False
        merged = merge_mailboxes(list(discovered), previous, provider_defaults=discovered)
        self.assertFalse(any(settings["sent_folder"] for settings in merged.values()))
        self.assertEqual(merge_mailboxes(list(discovered), {}, provider_defaults=discovered), discovered)

    def test_refresh_reads_registered_defaults_before_closing_adapter(self) -> None:
        """Populate labels for new provider folder IDs through the registered discovery hook."""
        from unittest.mock import Mock, patch

        from bloomerp.communication.builtins.emails.actions import (
            refresh_mailboxes_for_account,
        )
        from bloomerp.communication.builtins.emails.base_adapter import BaseEmailAdapter
        from bloomerp.models.communication.email_account import EmailAccount

        account = EmailAccount(mailboxes={})
        adapter = Mock()
        adapter.list_mailboxes.return_value = ["opaque-folder"]

        def provider_defaults(provider_adapter: BaseEmailAdapter) -> dict[str, dict[str, Any]]:
            """Read the discovery result while the shared service still owns the connection."""
            self.assertIs(provider_adapter, adapter)
            adapter.close.assert_not_called()
            return {"opaque-folder": {"label": "Inbox", "main_folder": True}}

        provider = Mock(mailbox_defaults=provider_defaults)
        with (
            patch("bloomerp.communication.builtins.emails.actions._resolve_provider", return_value=provider),
            patch("bloomerp.communication.builtins.emails.actions._resolve_email_adapter_for_account", return_value=adapter),
        ):
            names = refresh_mailboxes_for_account(account, save=False)
        self.assertEqual(names, ["opaque-folder"])
        self.assertEqual(account.mailboxes["opaque-folder"]["label"], "Inbox")
        self.assertTrue(account.mailboxes["opaque-folder"]["main_folder"])
        adapter.close.assert_called_once()
