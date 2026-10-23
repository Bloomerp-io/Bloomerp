import datetime
import imaplib
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from bloomerp.communication.builtins.emails.actions import (
    _upsert_email_inbox_item_result,
)
from bloomerp.communication.builtins.emails.base_adapter import (
    BaseEmailAdapter,
    BloomerpEmail,
    EmailSyncBatch,
)
from bloomerp.communication.builtins.emails.providers.imap_smtp import ImapSmtpAdapter
from bloomerp.communication.builtins.emails.sync import handle_email_account_sync
from bloomerp.communication.inbox_sources import InboxSourceExecutionResult
from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
from bloomerp.components.communication.emails.sync_emails import SyncEmailsForm
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem


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
        resolve_adapter: MagicMock,
    ) -> None:
        """
        Use case: A manual account sync supplies mailbox, date, and limit filters.
        Expected result: The registered provider receives those filters unchanged.
        """
        # 1. Execute the account source with explicit sync filters.
        start_date = datetime.date(2026, 7, 1)
        end_date = datetime.date(2026, 7, 21)
        adapter = BaseEmailAdapter(self.email_account)
        adapter.sync_emails = Mock(return_value=[])
        adapter.sync_batch = Mock(side_effect=AssertionError("Filtered sync must not consume delta state"))
        resolve_adapter.return_value = adapter
        pending, _ = _upsert_email_inbox_item_result(self._provider_email("pending"), self.folder)
        initial_cursor = {
            "mailboxes": {"INBOX": {"page": "unfinished"}},
            "pending_deletions": {"INBOX": ["pending"]},
            "pending_deliveries": {str(self.folder.pk): [str(pending.pk)]},
        }
        self.email_account.sync_cursor = initial_cursor
        self.email_account.save(update_fields=["sync_cursor"])
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
        adapter.sync_batch.assert_not_called()
        self.email_account.refresh_from_db()
        self.assertEqual(self.email_account.sync_cursor, initial_cursor)
        self.assertTrue(InboxItem.objects.filter(pk=pending.pk).exists())
        self.assertEqual(result.deliveries, ())

    def _provider_email(
        self,
        provider_message_id: str,
        *,
        mailbox: str = "INBOX",
        message_id: str | None = None,
    ) -> BloomerpEmail:
        """Build an account-scoped provider message for sync integration scenarios."""
        return BloomerpEmail(
            provider="imap",
            email_account_id=str(self.email_account.pk),
            provider_message_id=provider_message_id,
            provider_message_id_scope="account",
            mailbox=mailbox,
            message_id=message_id,
            subject=f"Message {provider_message_id}",
        )

    def _run_batches(
        self,
        batches: list[EmailSyncBatch | Exception],
        *,
        mailboxes: list[str] | None = None,
    ) -> InboxSourceExecutionResult:
        """Execute the real account source using deterministic provider pages."""
        adapter = BaseEmailAdapter(self.email_account)
        self.batch_mock = Mock(side_effect=batches)
        with (
            patch.object(adapter, "sync_batch", self.batch_mock),
            patch(
                "bloomerp.communication.builtins.emails.sync._resolve_email_adapter_for_account",
                return_value=adapter,
            ),
        ):
            return handle_email_account_sync(
                InboxFolder.objects.filter(related_object_id=str(self.email_account.pk)),
                email_account_id=str(self.email_account.pk),
                mailboxes=mailboxes,
            )

    def test_paged_sync_exhausts_backlog_and_replays_without_duplicates(self) -> None:
        """Import more than one page, checkpoint progress, and update replayed message flags."""
        emails = [self._provider_email(str(index)) for index in range(51)]
        result = self._run_batches([
            EmailSyncBatch(messages=emails[:50], cursor={"page": "second"}, has_more=True),
            EmailSyncBatch(messages=emails[50:], cursor={"delta": "finished"}),
        ])
        self.assertEqual(result.item_count, 51)
        self.assertTrue(result.plain_text_notifications)
        self.assertEqual(result.metrics["fetched_messages"], 51)
        self.assertEqual(self.batch_mock.call_args_list[1].kwargs["cursor"], {"page": "second"})
        self.email_account.refresh_from_db()
        self.assertEqual(self.email_account.sync_cursor, {"mailboxes": {"INBOX": {"delta": "finished"}}})
        self.assertIsNone(self.email_account.sync_locked_until)
        emails[0].is_read = True
        emails[0].message_id = "<first@example.com>"
        replay = self._run_batches([EmailSyncBatch(messages=[emails[0]], cursor={"delta": "updated"})])
        self.assertEqual(replay.deliveries, ())
        self.assertEqual(InboxItem.objects.filter(folder=self.folder).count(), 51)
        canonical = InboxItem.objects.get(raw_meta_data__provider_identity="0")
        self.assertTrue(canonical.is_read)
        self.assertEqual(canonical.related_item_id, emails[0].message_id)
        copied = emails[0].model_copy(update={"provider_message_id": "copy"})
        self.assertEqual(self._run_batches([EmailSyncBatch(messages=[copied])]).deliveries, ())
        self.assertEqual(InboxItem.objects.filter(folder=self.folder).count(), 51)

    def test_failed_page_resumes_checkpoint_and_pending_notifications(self) -> None:
        """Keep committed pages and their undelivered items when the provider fails later."""
        with self.assertRaisesMessage(RuntimeError, "provider unavailable"):
            self._run_batches([
                EmailSyncBatch(messages=[self._provider_email("first")], cursor={"page": "second"}, has_more=True),
                RuntimeError("provider unavailable"),
            ])
        self.email_account.refresh_from_db()
        self.assertEqual(self.email_account.sync_cursor["mailboxes"]["INBOX"], {"page": "second"})
        self.assertEqual(InboxItem.objects.filter(folder=self.folder).count(), 1)
        self.assertIsNone(self.email_account.sync_locked_until)
        self.assertEqual(self.email_account.last_sync_error, "provider unavailable")
        resumed = self._run_batches([
            EmailSyncBatch(messages=[self._provider_email("second")], cursor={"delta": "finished"}),
        ])
        self.assertEqual(self.batch_mock.call_args.kwargs["cursor"], {"page": "second"})
        self.assertEqual(resumed.item_count, 2)
        self.email_account.refresh_from_db()
        self.assertNotIn("pending_deliveries", self.email_account.sync_cursor)

    def test_failed_local_upsert_rolls_back_items_and_cursor_for_all_inboxes(self) -> None:
        """Do not acknowledge a provider page unless every linked inbox stores its messages."""
        InboxFolder.objects.create(
            inbox=self.folder.inbox,
            type=INBOX_FOLDER_REGISTRY.EMAIL.key,
            related_object_id=str(self.email_account.pk),
        )
        completed_upserts = 0

        def fail_second_inbox(email: BloomerpEmail, folder: InboxFolder) -> tuple[InboxItem, bool]:
            """Fail after the first inbox write to exercise the enclosing page transaction."""
            nonlocal completed_upserts
            completed_upserts += 1
            if completed_upserts == 2:
                raise RuntimeError("local write failed")
            return _upsert_email_inbox_item_result(email, folder)

        with (
            patch(
                "bloomerp.communication.builtins.emails.sync._upsert_email_inbox_item_result",
                side_effect=fail_second_inbox,
            ),
            self.assertRaisesMessage(RuntimeError, "local write failed"),
        ):
            self._run_batches([
                EmailSyncBatch(messages=[self._provider_email("first")], cursor={"delta": "finished"}),
            ])
        self.email_account.refresh_from_db()
        self.assertEqual(self.email_account.sync_cursor, {})
        self.assertFalse(InboxItem.objects.filter(folder=self.folder).exists())
        self.assertIsNone(self.email_account.sync_locked_until)

    def test_move_tombstones_preserve_identity_in_either_mailbox_order(self) -> None:
        """Reconcile account-scoped moves without losing rows or notifying them again."""
        for mailboxes in (["INBOX", "Archive"], ["Archive", "INBOX"]):
            with self.subTest(mailboxes=mailboxes):
                InboxItem.objects.filter(folder=self.folder).delete()
                item, _ = _upsert_email_inbox_item_result(self._provider_email("immutable"), self.folder)
                batches = {
                    "INBOX": EmailSyncBatch(deleted_message_ids=["immutable"], cursor={"delta": "inbox"}),
                    "Archive": EmailSyncBatch(messages=[self._provider_email("immutable", mailbox="Archive")], cursor={"delta": "archive"}),
                }
                if mailboxes[0] == "Archive":
                    # A source tombstone can discover a move after its destination was scanned.
                    batches["INBOX"].messages = batches["Archive"].messages
                    batches["Archive"].messages = []
                result = self._run_batches([batches[mailbox] for mailbox in mailboxes], mailboxes=mailboxes)
                item.refresh_from_db()
                self.assertEqual(set(item.raw_meta_data["locations"]), {"Archive"})
                self.assertEqual(InboxItem.objects.filter(folder=self.folder).count(), 1)
                self.assertEqual(result.deliveries, ())
                self._run_batches([batches["INBOX"]], mailboxes=["INBOX"])
                self.assertTrue(InboxItem.objects.filter(pk=item.pk).exists())
                self._run_batches([EmailSyncBatch(deleted_message_ids=["immutable"])], mailboxes=["Archive"])
                self.assertFalse(InboxItem.objects.filter(pk=item.pk).exists())

    def test_reset_snapshot_keeps_later_pages_and_removes_absent_messages(self) -> None:
        """Reconcile an expired cursor only after every replacement snapshot page succeeds."""
        stale, _ = _upsert_email_inbox_item_result(self._provider_email("gone"), self.folder)
        retained, _ = _upsert_email_inbox_item_result(self._provider_email("retained"), self.folder)
        with self.assertRaisesMessage(RuntimeError, "interrupted snapshot"):
            self._run_batches([
                EmailSyncBatch(messages=[self._provider_email("new")], cursor={"page": "next"}, has_more=True, reset=True),
                RuntimeError("interrupted snapshot"),
            ])
        self.assertTrue(InboxItem.objects.filter(pk=stale.pk).exists())
        result = self._run_batches([
            EmailSyncBatch(messages=[self._provider_email("retained")], cursor={"delta": "finished"}),
        ])
        self.assertFalse(InboxItem.objects.filter(pk=stale.pk).exists())
        self.assertTrue(InboxItem.objects.filter(pk=retained.pk).exists())
        self.assertEqual(InboxItem.objects.filter(folder=self.folder).count(), 2)
        self.assertEqual(result.item_count, 1)

    def test_disabled_accounts_and_disconnect_during_fetch_cannot_import(self) -> None:
        """Prevent queued or in-flight work from writing messages after account disconnection."""
        self.email_account.sync_enabled = False
        self.email_account.save(update_fields=["sync_enabled"])
        result = self._run_batches([])
        self.assertEqual(result.reason, "account_unavailable")
        self.batch_mock.assert_not_called()
        self.email_account.sync_enabled = True
        self.email_account.save(update_fields=["sync_enabled"])
        adapter = BaseEmailAdapter(self.email_account)

        def disconnect_during_fetch(**kwargs: Any) -> EmailSyncBatch:
            """Simulate account disconnection while the provider request is in flight."""
            EmailAccount.objects.filter(pk=self.email_account.pk).update(
                status=EmailAccount.Status.DRAFT, sync_enabled=False, next_sync_at=None,
            )
            return EmailSyncBatch(messages=[self._provider_email("late")], cursor={"delta": "late"})

        with (
            patch.object(adapter, "sync_batch", side_effect=disconnect_during_fetch),
            patch("bloomerp.communication.builtins.emails.sync._resolve_email_adapter_for_account", return_value=adapter),
        ):
            result = handle_email_account_sync(
                InboxFolder.objects.filter(pk=self.folder.pk),
                email_account_id=str(self.email_account.pk),
            )
        self.email_account.refresh_from_db()
        self.assertEqual(result.reason, "account_unavailable")
        self.assertEqual(self.email_account.sync_cursor, {})
        self.assertIsNone(self.email_account.next_sync_at)
        self.assertIsNone(self.email_account.sync_locked_until)
        self.assertFalse(InboxItem.objects.filter(folder=self.folder).exists())
