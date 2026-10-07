from importlib import import_module
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from bloomerp.celery.tasks.inbox_source_task import execute_inbox_source_task
from bloomerp.communication.builtins.emails.actions import query_emails, render_email
from bloomerp.communication.builtins.emails.base_adapter import BloomerpEmail
from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
from bloomerp.communication.inbox_sources import (
    InboxEventSource,
    InboxJobSource,
    InboxSourceReceipt,
    InboxSourceRegistry,
    execute_registered_source,
    publish_event,
    synchronize_job_schedules,
)
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem


class InboxSourceRegistryTests(TestCase):
    def test_default_sources_are_discoverable_and_resolve_callables(self) -> None:
        """
        Use case: The application loads its built-in inbox sources.
        Expected result: Registered sources expose resolved handlers and resolvers.
        """
        # 1. Resolve the default email job and account event.
        job = InboxSourceRegistry.get_by_key("email.sync.dispatch")
        account_event = InboxSourceRegistry.get_by_key("email.sync.account")

        # 2. Verify their contracts and source types.
        self.assertEqual(job.folder_type, INBOX_FOLDER_REGISTRY.EMAIL.key)
        self.assertIsInstance(job.source, InboxJobSource)
        self.assertTrue(callable(job.source.resolve_folder_qs_resolver()))
        self.assertTrue(callable(job.source.resolve_handler()))
        self.assertIsInstance(account_event.source, InboxEventSource)

    def test_job_schedule_is_created_from_registered_source(self):
        """
        Use case: Inbox source schedules are synchronized with Celery Beat.
        Expected result: Email polling is registered to run every two minutes.
        """
        # 1. Synchronize source schedules.
        synchronize_job_schedules()

        # 2. Verify the generated Celery Beat task and interval.
        task = PeriodicTask.objects.get(
            name="bloomerp.inbox_source.email.sync.dispatch"
        )
        self.assertEqual(
            task.task,
            "bloomerp.celery.tasks.inbox_source_task.execute_inbox_source_task",
        )
        self.assertEqual(task.args, '["email.sync.dispatch"]')
        self.assertEqual(task.crontab.minute, "*/2")


class EmailInboxSourceTests(TestCase):
    def setUp(self) -> None:
        """Create inbox sources and users for notification and email synchronization."""
        self.user = get_user_model().objects.create_user(
            username="email-source-user",
            email="email-source-user@example.com",
            password="password",
        )
        self.inbox = Inbox.objects.create(user=self.user, name="Email inbox")
        self.email_account = EmailAccount.objects.create(
            name="Support",
            email_address="support-source@example.com",
            status=EmailAccount.Status.ACTIVE,
            sync_enabled=True,
        )
        self.folder = InboxFolder.objects.create(
            inbox=self.inbox,
            type=INBOX_FOLDER_REGISTRY.EMAIL.key,
            related_object_id=str(self.email_account.id),
        )
        self.notification_folder = InboxFolder.objects.create(
            inbox=self.inbox,
            type=INBOX_FOLDER_REGISTRY.IN_APP_NOTIFICATIONS.key,
        )

    def _provider_email(
        self,
        *,
        provider_message_id: str = "provider-message-1",
        mailbox: str = "INBOX",
        message_id: str | None = None,
    ) -> BloomerpEmail:
        return BloomerpEmail(
            provider=self.email_account.provider,
            provider_message_id=provider_message_id,
            email_account_id=str(self.email_account.id),
            mailbox=mailbox,
            message_id=message_id,
            subject="Architecture test",
            sender="sender@example.com",
            date=timezone.now(),
            snippet="Inbox source delivery",
        )

    @patch("bloomerp.communication.inbox_sources.send_user_inbox_message")
    def test_event_source_resolves_folders_and_forwards_keyword_payload(
        self,
        send_user_inbox_message,
    ):
        """
        Use case: A system message event targets a specific user.
        Expected result: The source resolves the folder and forwards its payload.
        """
        # 1. Publish a general system message event.
        receipt = publish_event(
            "system.message",
            user_ids=[self.user.id],
            system_message_type="general",
            data={"message": "Persistent message", "severity": "info"},
        )

        # 2. Verify persistence in the resolved folder and one broadcast.
        self.assertEqual(receipt.state, "completed")
        self.assertIsNotNone(receipt.result)
        self.assertEqual(receipt.result.delivery_count, 1)
        item = receipt.result.deliveries[0].items[0]
        self.assertEqual(item.folder, self.notification_folder)
        self.assertEqual(item.snippet, "Persistent message")
        send_user_inbox_message.assert_called_once()

    def test_async_event_returns_a_correlatable_scheduled_receipt(self):
        """
        Use case: An asynchronous inbox event is published while Celery is available.
        Expected result: The caller receives a scheduled receipt with the Celery task ID.
        """
        # 1. Publish the account event and execute its transaction callback.
        with (
            patch(
                "bloomerp.communication.inbox_sources.is_celery_available",
                return_value=True,
            ),
            patch(
                "bloomerp.celery.tasks.inbox_source_task."
                "execute_inbox_source_task.apply_async"
            ) as apply_async,
            self.captureOnCommitCallbacks(execute=True),
        ):
            receipt = publish_event(
                "email.sync.account",
                email_account_id=str(self.email_account.id),
            )

        # 2. Verify the receipt and queued task share one execution identifier.
        self.assertEqual(receipt.state, "scheduled")
        self.assertIsNone(receipt.result)
        self.assertEqual(
            apply_async.call_args.kwargs["task_id"],
            str(receipt.execution_id),
        )
        self.assertEqual(
            apply_async.call_args.kwargs["args"][0],
            "email.sync.account",
        )

    @patch("bloomerp.communication.inbox_sources.send_user_inbox_message")
    @patch(
        "bloomerp.communication.builtins.emails.sync._resolve_email_adapter_for_account"
    )
    def test_account_source_creates_and_delivers_only_new_items(
        self,
        resolve_adapter,
        send_user_inbox_message,
    ):
        """
        Use case: The same provider email is returned by consecutive syncs.
        Expected result: Only the first sync creates and broadcasts an inbox item.
        """
        # 1. Return the same provider email for both sync passes.
        resolve_adapter.return_value.sync_emails.return_value = [self._provider_email()]

        # 2. Execute the registered account source twice.
        first_result = execute_registered_source(
            "email.sync.account",
            email_account_id=str(self.email_account.id),
        )
        second_result = execute_registered_source(
            "email.sync.account",
            email_account_id=str(self.email_account.id),
        )

        # 3. Verify idempotent persistence and delivery.
        self.assertEqual(first_result.delivery_count, 1)
        self.assertEqual(first_result.item_count, 1)
        self.assertEqual(second_result.deliveries, ())
        self.assertEqual(InboxItem.objects.filter(folder=self.folder).count(), 1)
        send_user_inbox_message.assert_called_once()

    @patch("bloomerp.communication.inbox_sources.send_user_inbox_message")
    @patch("bloomerp.communication.builtins.emails.sync._resolve_email_adapter_for_account")
    def test_sent_mailbox_sync_persists_without_notifications(
        self, resolve_adapter: MagicMock, send_user_inbox_message: MagicMock,
    ) -> None:
        """Sync a custom-named Sent mailbox without broadcasting its newly stored email."""
        self.email_account.mailboxes = {
            "Outgoing": {"label": "Sent", "sent_folder": True},
        }
        self.email_account.save(update_fields=["mailboxes"])
        resolve_adapter.return_value.sync_emails.return_value = [
            self._provider_email(mailbox="Outgoing"),
        ]

        result = execute_registered_source(
            "email.sync.account", email_account_id=str(self.email_account.pk),
        )

        self.assertEqual(result.deliveries, ())
        self.assertEqual(result.metrics["fetched_messages"], 1)
        self.assertEqual(InboxItem.objects.filter(folder=self.folder).count(), 1)
        send_user_inbox_message.assert_not_called()

    @patch("bloomerp.communication.inbox_sources.send_user_inbox_message")
    @patch("bloomerp.communication.builtins.emails.sync._resolve_email_adapter_for_account")
    def test_sent_alias_is_silent_regardless_of_sync_order(
        self, resolve_adapter: MagicMock, send_user_inbox_message: MagicMock,
    ) -> None:
        """Notify an incoming email while suppressing another message also found in Sent."""
        self.email_account.mailboxes = {
            "INBOX": {"label": "Inbox", "main_folder": True},
            "Outgoing": {"label": "Sent", "sent_folder": True},
        }
        self.email_account.save(update_fields=["mailboxes"])
        incoming = self._provider_email(
            provider_message_id="incoming", message_id="<incoming@example.com>",
        )
        shared_inbox = self._provider_email(
            provider_message_id="inbox-copy", message_id="<outbound@example.com>",
        )
        shared_sent = self._provider_email(
            provider_message_id="sent-copy", mailbox="Outgoing", message_id="<outbound@example.com>",
        )
        for mailboxes in (["INBOX", "Outgoing"], ["Outgoing", "INBOX"]):
            with self.subTest(mailboxes=mailboxes):
                InboxItem.objects.filter(folder=self.folder).delete()
                send_user_inbox_message.reset_mock()
                resolve_adapter.return_value.sync_emails.side_effect = [
                    [incoming, shared_inbox] if mailbox == "INBOX" else [shared_sent]
                    for mailbox in mailboxes
                ]
                result = execute_registered_source(
                    "email.sync.account", email_account_id=str(self.email_account.pk),
                    mailboxes=mailboxes,
                )
                self.assertEqual(result.item_count, 1)
                self.assertEqual(result.deliveries[0].items[0].related_item_id, incoming.message_id)
                self.assertEqual(InboxItem.objects.filter(folder=self.folder).count(), 2)
                shared_item = InboxItem.objects.get(folder=self.folder, related_item_id=shared_sent.message_id)
                self.assertEqual(set(shared_item.raw_meta_data["locations"]), {"INBOX", "Outgoing"})
                send_user_inbox_message.assert_called_once()

    @patch("bloomerp.communication.inbox_sources.send_user_inbox_message")
    @patch(
        "bloomerp.communication.builtins.emails.sync._resolve_email_adapter_for_account"
    )
    def test_same_message_in_multiple_mailboxes_has_one_inbox_item(
        self,
        resolve_adapter,
        send_user_inbox_message,
    ):
        """
        Use case: IMAP exposes one Message-ID under INBOX and All Mail UIDs.
        Expected result: One inbox item retains both retrieval locations.
        """
        # 1. Return the same message from two mailboxes with different UIDs.
        message_id = "<FZL6fsJYQWec7VIzuomhyg@geopod-ismtpd-104>"
        resolve_adapter.return_value.sync_emails.side_effect = [
            [
                self._provider_email(
                    provider_message_id="2587",
                    mailbox="INBOX",
                    message_id=message_id,
                )
            ],
            [
                self._provider_email(
                    provider_message_id="4636",
                    mailbox="[Gmail]/All Mail",
                    message_id=message_id,
                )
            ],
        ]

        result = execute_registered_source(
            "email.sync.account",
            email_account_id=str(self.email_account.id),
            mailboxes=["INBOX", "[Gmail]/All Mail"],
        )

        # 2. Verify Message-ID identity and both JSON retrieval locations.
        self.assertEqual(result.item_count, 1)
        item = InboxItem.objects.get(folder=self.folder)
        self.assertEqual(item.related_item_id, message_id)
        self.assertEqual(
            item.raw_meta_data["locations"],
            {
                "INBOX": {
                    "mailbox": "INBOX",
                    "provider_message_id": "2587",
                    "flags": [],
                    "raw": {},
                },
                "[Gmail]/All Mail": {
                    "mailbox": "[Gmail]/All Mail",
                    "provider_message_id": "4636",
                    "flags": [],
                    "raw": {},
                },
            },
        )

        # 3. Verify both mailbox filters resolve the canonical item.
        self.assertEqual(
            query_emails({"mailbox": "INBOX"}, self.folder, False).get(),
            item,
        )
        self.assertEqual(
            query_emails(
                {"mailbox": "[Gmail]/All Mail"},
                self.folder,
                False,
            ).get(),
            item,
        )
        send_user_inbox_message.assert_called_once()

        # 4. Verify content retrieval uses the preferred INBOX UID.
        with patch(
            "bloomerp.communication.builtins.emails.actions."
            "_resolve_email_adapter_for_account"
        ) as resolve_render_adapter:
            resolve_render_adapter.return_value.fetch_email_content.return_value = (
                "rendered email"
            )
            self.assertIn("rendered email", render_email(item, None))
            resolve_render_adapter.return_value.fetch_email_content.assert_called_once_with(
                email_id="2587",
                mailbox="INBOX",
            )

    def test_email_migration_consolidates_existing_message_id_duplicates(self) -> None:
        """
        Use case: Existing rows use mailbox-specific UIDs for one Message-ID.
        Expected result: Migration keeps one item and merges both JSON locations.
        """
        # 1. Create the two legacy rows from the production example.
        message_id = "<legacy-duplicate@example.com>"
        for mailbox, provider_message_id in (
            ("INBOX", "2587"),
            ("[Gmail]/All Mail", "4636"),
        ):
            InboxItem.objects.create(
                folder=self.folder,
                item_type=INBOX_FOLDER_REGISTRY.EMAIL.item_type.key,
                related_item_id=provider_message_id,
                title="Legacy duplicate",
                raw_meta_data={
                    "provider": "imap",
                    "email_account_id": str(self.email_account.pk),
                    "mailbox": mailbox,
                    "provider_message_id": provider_message_id,
                    "message_id": message_id,
                },
            )

        # 2. Execute the data migration operation.
        migration = import_module(
            "bloomerp.migrations.0047_consolidate_email_message_ids"
        )
        migration.consolidate_email_message_ids(apps, None)

        # 3. Verify the duplicate was consolidated without losing either UID.
        item = InboxItem.objects.get(folder=self.folder)
        self.assertEqual(item.related_item_id, message_id)
        self.assertEqual(
            {
                mailbox: location["provider_message_id"]
                for mailbox, location in item.raw_meta_data["locations"].items()
            },
            {
                "INBOX": "2587",
                "[Gmail]/All Mail": "4636",
            },
        )

    @patch("bloomerp.communication.builtins.emails.sync.publish_event")
    def test_dispatch_source_queues_each_due_account(self, publish):
        """
        Use case: The scheduled email dispatch source runs for a due account.
        Expected result: It publishes an account event and reports scheduling metrics.
        """
        # 1. Execute the scheduled dispatch source.
        publish.return_value = InboxSourceReceipt(
            source_key="email.sync.account",
            execution_id=uuid4(),
            state="scheduled",
        )
        result = execute_registered_source("email.sync.dispatch")

        # 2. Verify asynchronous delegation and descriptive execution metrics.
        self.assertEqual(result.deliveries, ())
        self.assertEqual(result.metrics["scheduled_accounts"], 1)
        publish.assert_called_once_with(
            "email.sync.account",
            email_account_id=str(self.email_account.id),
        )

    @patch("bloomerp.communication.inbox_sources.send_user_inbox_message")
    @patch(
        "bloomerp.communication.builtins.emails.sync._resolve_email_adapter_for_account"
    )
    def test_account_task_executes_registered_inbox_source(
        self,
        resolve_adapter,
        send_user_inbox_message,
    ):
        """
        Use case: Celery executes an email account synchronization.
        Expected result: The task delegates to the source and reports its result.
        """
        # 1. Configure the provider response and execute the Celery adapter.
        resolve_adapter.return_value.sync_emails.return_value = [self._provider_email()]

        result = execute_inbox_source_task.run(
            "email.sync.account",
            serialized_kwargs={
                "email_account_id": str(self.email_account.id),
            },
            execution_id=str(uuid4()),
        )

        # 2. Verify the source result and persisted inbox item.
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(result["item_count"], 1)
        self.assertEqual(InboxItem.objects.filter(folder=self.folder).count(), 1)
