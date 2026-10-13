import datetime
import imaplib
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from bloomerp.communication.builtins.emails.providers.imap_smtp import ImapSmtpAdapter
from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
from bloomerp.communication.builtins.emails.sync import handle_email_account_sync
from bloomerp.components.communication.emails.sync_emails import SyncEmailsForm
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder


class SyncEmailsFormTests(SimpleTestCase):
    def test_all_mailboxes_are_selected_initially(self):
        mailboxes = ["INBOX", "[Gmail]/Sent Mail"]

        form = SyncEmailsForm(mailboxes=mailboxes)

        self.assertEqual(form["mailboxes"].value(), mailboxes)

    def test_bound_form_preserves_an_empty_mailbox_selection(self):
        form = SyncEmailsForm(
            data={},
            mailboxes=["INBOX", "[Gmail]/Sent Mail"],
        )

        self.assertIsNone(form["mailboxes"].value())
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["mailboxes"], [])


class ImapMailboxDiscoveryTests(SimpleTestCase):
    def test_list_mailboxes_excludes_noselect_hierarchy_containers(self):
        adapter = ImapSmtpAdapter(SimpleNamespace())
        connection = Mock()
        connection.list.return_value = (
            "OK",
            [
                br'(\HasNoChildren) "/" "INBOX"',
                br'(\HasChildren \Noselect) "/" "[Gmail]"',
                br'(\HasNoChildren) "/" "[Gmail]/Sent Mail"',
            ],
        )
        adapter.connect = Mock(return_value=connection)

        self.assertEqual(
            adapter.list_mailboxes(),
            ["INBOX", "[Gmail]/Sent Mail"],
        )

    def test_select_mailbox_quotes_names_containing_spaces(self):
        adapter = ImapSmtpAdapter(SimpleNamespace())
        connection = Mock()
        connection.select.return_value = ("OK", [b"1"])
        adapter.connect = Mock(return_value=connection)

        adapter._select_mailbox("[Gmail]/All Mail", readonly=True)

        connection.select.assert_called_once_with(
            '"[Gmail]/All Mail"',
            readonly=True,
        )

    def test_select_mailbox_converts_imap_errors_to_validation_errors(self):
        adapter = ImapSmtpAdapter(SimpleNamespace())
        connection = Mock()
        connection.select.side_effect = imaplib.IMAP4.error(
            "EXAMINE command error"
        )
        adapter.connect = Mock(return_value=connection)

        with self.assertRaisesMessage(
            ValidationError,
            "Unable to select mailbox [Gmail]/All Mail",
        ):
            adapter._select_mailbox("[Gmail]/All Mail", readonly=True)


class EmailSyncSourceTests(TestCase):
    def setUp(self) -> None:
        """Create a connected email folder for synchronization tests."""
        user = get_user_model().objects.create_user(
            username="email-filter-user",
            email="email-filter-user@example.com",
            password="password",
        )
        inbox = Inbox.objects.create(user=user, name="Email inbox")
        self.email_account = EmailAccount.objects.create(
            email_address="email-filter-account@example.com",
            status=EmailAccount.Status.ACTIVE,
            sync_enabled=True,
            mailboxes=["INBOX"],
        )
        self.folder = InboxFolder.objects.create(
            inbox=inbox,
            type=INBOX_FOLDER_REGISTRY.EMAIL.key,
            related_object_id=str(self.email_account.pk),
        )

    @patch(
        "bloomerp.communication.builtins.emails.sync._resolve_email_adapter_for_account"
    )
    def test_account_sync_forwards_action_filters(
        self,
        resolve_adapter,
    ):
        """
        Use case: A manual account sync supplies mailbox, date, and limit filters.
        Expected result: The registered provider receives those filters unchanged.
        """
        # 1. Execute the account source with explicit sync filters.
        start_date = datetime.date(2026, 7, 1)
        end_date = datetime.date(2026, 7, 21)
        adapter = resolve_adapter.return_value
        adapter.sync_emails.return_value = []
        result = handle_email_account_sync(
            InboxFolder.objects.filter(pk=self.folder.pk),
            email_account_id=str(self.email_account.pk),
            from_date=start_date,
            to_date=end_date,
            limit=25,
            mailboxes=["INBOX"],
        )

        # 2. Verify the provider call and the descriptive source result.
        adapter.sync_emails.assert_called_once_with(
            from_date=start_date,
            to_date=end_date,
            limit=25,
            mailbox="INBOX",
        )
        self.assertEqual(result.outcome, "completed")
        self.assertEqual(result.metrics["fetched_messages"], 0)
