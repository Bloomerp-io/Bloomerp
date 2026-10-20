"""Integration coverage for durable mention delivery and its security boundaries."""

from unittest.mock import patch
from uuid import uuid4

from django.db import connection, transaction
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from bloomerp.communication.builtins.in_app_notifications.base import SystemMessage
from bloomerp.models import ApplicationField, Comment, Mention
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.models.project_management.todo import Todo
from bloomerp.services.object_reference_services import Reference, reconcile_references
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestMentionNotifications(BaseBloomerpTestCaseWithModels):
    """Exercise atomic reconciliation, notification snapshots and normal navigation."""

    auto_create_customers = False

    def extendedSetup(self) -> None:
        """Prepare a real source and recipient inbox with no external message transport."""
        self.sender = self.admin_user
        self.recipient = self.normal_user
        self.recipient.is_staff = True
        self.recipient.save(update_fields=["is_staff"])
        self.todo = Todo.objects.create(title="Restricted project")
        self.field = ApplicationField.get_by_field(Todo, "content")
        self.inbox = Inbox.objects.get(user=self.recipient, selected=True)
        self.folder = InboxFolder.objects.get(
            inbox=self.inbox, type="in_app_notifications"
        )
        self.request = RequestFactory().post("/")
        self.request.user = self.sender
        self.transport = patch(
            "bloomerp.communication.inbox_sources.send_user_inbox_message"
        )
        self.broadcast = self.transport.start()
        self.addCleanup(self.transport.stop)

    def reference(self, *, inline: bool = False) -> Reference:
        """Return a manual mention or a fresh occurrence of the same recipient."""
        return Reference(
            "user",
            str(self.recipient.pk),
            field_id=self.field.pk if inline else None,
            occurrence_id=uuid4() if inline else None,
        )

    def items(self) -> list[InboxItem]:
        """Read only notification items created for the intended recipient."""
        return list(InboxItem.objects.filter(folder=self.folder).order_by("pk"))

    def test_new_manual_and_field_scopes_notify_once(self) -> None:
        """Resaves, duplicate occurrences and regenerated occurrence IDs remain silent."""
        fields = {
            self.field.pk: [self.reference(inline=True), self.reference(inline=True)]
        }
        manual = [self.reference()]
        reconcile_references(self.todo, fields, manual, self.request)
        self.assertEqual(len(self.items()), 2)
        self.assertEqual(
            {item.raw_meta_data["field_label"] for item in self.items()},
            {"", "Content"},
        )
        for item in self.items():
            self.assertIn("mentioned you in Restricted project", item.snippet)
            self.assertEqual(item.raw_meta_data["url"], self.todo.get_absolute_url())
        self.broadcast.reset_mock()
        with CaptureQueriesContext(connection) as queries:
            reconcile_references(self.todo, fields, manual, self.request)
        self.assertEqual(len(self.items()), 2)
        self.broadcast.assert_not_called()
        self.assertFalse(
            any("bloomerp_inbox" in query["sql"].lower() for query in queries)
        )
        reconcile_references(
            self.todo,
            {self.field.pk: [self.reference(inline=True)]},
            manual,
            self.request,
        )
        self.assertEqual(len(self.items()), 2)

    def test_removing_mention_keeps_snapshot_and_readding_notifies(self) -> None:
        """Deletion never removes old inbox history; a later fresh mention can notify."""
        reconcile_references(self.todo, {}, [self.reference()], self.request)
        reconcile_references(self.todo, {}, [], self.request)
        self.assertEqual(len(self.items()), 1)
        self.assertFalse(Mention.objects.exists())
        reconcile_references(self.todo, {}, [self.reference()], self.request)
        self.assertEqual(len(self.items()), 2)

    def test_rollback_removes_mentions_and_notifications(self) -> None:
        """An enclosing failed object save cannot leave a persisted inbox item."""
        with self.assertRaises(ValueError), transaction.atomic():
            reconcile_references(self.todo, {}, [self.reference()], self.request)
            raise ValueError("Simulate a later save failure")
        self.assertEqual(self.items(), [])
        self.assertFalse(Mention.objects.exists())
        self.broadcast.assert_not_called()

    def test_commit_delivers_realtime_after_persistence(self) -> None:
        """A committed mention sends exactly one realtime update after persistence."""
        with transaction.atomic():
            reconcile_references(self.todo, {}, [self.reference()], self.request)
            self.assertEqual(len(self.items()), 1)
            self.broadcast.assert_not_called()
        self.broadcast.assert_called_once()

    def test_comment_snapshot_and_permission_checked_deep_link(self) -> None:
        """Comment content stays private and navigation retains the parent permission gate."""
        comment = Comment.objects.create(
            content_object=self.todo, content="Secret body", created_by=self.sender
        )
        field = ApplicationField.get_by_field(Comment, "content")
        reconcile_references(
            comment,
            {
                field.pk: [
                    Reference(
                        "user",
                        str(self.recipient.pk),
                        field_id=field.pk,
                        occurrence_id=uuid4(),
                    )
                ]
            },
            None,
            self.request,
        )
        item = self.items()[0]
        self.assertIn("Restricted project (Comment)", item.snippet)
        self.assertNotIn("Secret body", item.snippet)
        self.assertEqual(item.raw_meta_data["url"], comment.get_absolute_url())
        self.client.force_login(self.recipient)
        self.assertEqual(self.client.get(item.raw_meta_data["url"]).status_code, 404)
        self.client.force_login(self.sender)
        response = self.client.get(item.raw_meta_data["url"])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{self.todo.get_absolute_url()}?sidebar=comments&comment={comment.pk}#comment-{comment.pk}",
        )

    def test_recipient_can_read_snapshot_without_object_access(self) -> None:
        """Inbox labels are allowed, while following the object URL grants no new access."""
        reconcile_references(self.todo, {}, [self.reference()], self.request)
        item = self.items()[0]
        request = RequestFactory().get("/")
        request.user = self.recipient
        html = SystemMessage.resolve_render(item, request=request)
        self.assertIn("Restricted project", html)
        self.client.force_login(self.recipient)
        self.assertIn(
            self.client.get(item.raw_meta_data["url"]).status_code, (403, 404)
        )

    def test_shared_foreign_inbox_is_not_a_delivery_destination(self) -> None:
        """Mentioning a shared-inbox reader must not disclose the label to its owner."""
        foreign = Inbox.objects.create(user=self.sender, name="Team", selected=True)
        foreign.shared_with_users.add(self.recipient)
        folder = InboxFolder.objects.create(inbox=foreign, type="in_app_notifications")
        reconcile_references(self.todo, {}, [self.reference()], self.request)
        self.assertEqual(len(self.items()), 1)
        self.assertFalse(InboxItem.objects.filter(folder=folder).exists())

    def test_render_escapes_snapshot_and_rejects_unsafe_navigation(self) -> None:
        """Persisted display labels cannot execute markup or supply external links."""
        item = SystemMessage.create_item(
            message_type="mention",
            folder=self.folder,
            data={
                "actor_label": "<script>bad()</script>",
                "object_label": "<img src=x onerror=bad()>",
                "url": "javascript:bad()",
            },
        )
        html = SystemMessage.resolve_render(item)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("href=", html)
        self.assertIn("&lt;script&gt;", html)
        for url in ("//evil.example/path", "/\\evil.example", "https://evil.example"):
            item.raw_meta_data["url"] = url
            self.assertNotIn("href=", SystemMessage.resolve_render(item))

    def test_deleted_source_does_not_break_snapshot(self) -> None:
        """Notification rendering needs no surviving object or mention row."""
        reconcile_references(self.todo, {}, [self.reference()], self.request)
        self.todo.delete()
        self.assertIn(
            "Restricted project", SystemMessage.resolve_render(self.items()[0])
        )

    def test_realtime_escapes_untrusted_object_label(self) -> None:
        """The HTML-capable toast transport must receive escaped mention text."""
        self.todo.title = '<img src=x onerror="bad()">'
        self.todo.save()
        with transaction.atomic():
            reconcile_references(self.todo, {}, [self.reference()], self.request)
        message = self.broadcast.call_args.kwargs["payload"].toast_payload.message
        self.assertNotIn("<img", message)
        self.assertIn("&lt;img", message)

    def test_owned_shared_inbox_keeps_existing_sharing_permissions(self) -> None:
        """Owner-authorized sharing still exposes ordinary notification items."""
        from bloomerp.communication.utils.permissions import accessible_inbox_items

        self.inbox.shared_with_users.add(self.sender)
        with transaction.atomic():
            reconcile_references(self.todo, {}, [self.reference()], self.request)
        self.assertEqual(len(self.items()), 1)
        self.assertTrue(
            accessible_inbox_items(self.sender).filter(pk=self.items()[0].pk).exists()
        )
        self.assertEqual(
            {call.args[0] for call in self.broadcast.call_args_list},
            {self.sender.pk, self.recipient.pk},
        )


    def test_equivalent_recipient_ids_do_not_bypass_deduplication(self) -> None:
        """Canonical user IDs prevent repeated notifications for alternate numeric input."""
        reference = Reference("user", f"0{self.recipient.pk}")
        reconcile_references(self.todo, {}, [reference], self.request)
        reconcile_references(self.todo, {}, [reference], self.request)
        self.assertEqual(len(self.items()), 1)
