"""Integration coverage for calendar MIME, inbox synchronization, and SMTP delivery."""

from datetime import timedelta
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from bloomerp.communication.builtins.emails.base_adapter import (
    BloomerpEmail,
    EmailAttachment,
    EmailSendResult,
    EmailSendUnconfirmed,
)
from bloomerp.communication.builtins.emails.providers.imap_smtp import ImapSmtpAdapter
from bloomerp.communication.builtins.emails.sync import handle_email_account_sync
from bloomerp.communication.calendar.ical import parse_scheduling_message
from bloomerp.communication.calendar.mime import (
    add_calendar_alternative,
    extract_calendar_parts,
)
from bloomerp.communication.calendar.outgoing import (
    respond_to_calendar_invitation,
    send_calendar_request,
    send_removed_calendar_cancellations,
)
from bloomerp.models.communication.calendar import (
    CalendarEvent,
    CalendarSchedulingCancellation,
)
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.views.communication.calendar.cancel import cancel_calendar_event

from .calendar_fixtures import STAMP, UID, SchedulingFixtures


class CalendarMimeTests(SimpleTestCase):
    """Exercise real email MIME parsing and SMTP message construction."""

    def test_calendar_body_and_attachment_are_detected_without_filenames(self) -> None:
        """Read text/calendar alternatives and attachment parts by their MIME type."""
        message = EmailMessage()
        message.set_content("Invitation")
        message.add_alternative(
            "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
            subtype="calendar",
            params={"method": "REQUEST"},
        )
        message.add_attachment(
            b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
            maintype="text",
            subtype="calendar",
            params={"method": "REPLY"},
        )
        parts = extract_calendar_parts(message)
        self.assertEqual([part.method for part in parts], ["REQUEST", "REPLY"])

    def test_forwarded_messages_and_ordinary_attachments_are_not_scheduling(
        self,
    ) -> None:
        """Do not interpret ordinary attachments based on an ICS-looking file name."""
        message = EmailMessage()
        message.set_content("Ordinary message")
        message.add_attachment(
            b"not a calendar",
            maintype="application",
            subtype="octet-stream",
            filename="invite.ics",
        )
        self.assertEqual(extract_calendar_parts(message), [])

    def test_outgoing_calendar_is_a_method_bearing_alternative(self) -> None:
        """Create an iMIP alternative alongside plain text and HTML."""
        message = EmailMessage()
        message.set_content("Invitation")
        message.add_alternative("<p>Invitation</p>", subtype="html")
        add_calendar_alternative(
            message,
            EmailAttachment(
                filename="invite.ics",
                content=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
                content_type="text/calendar",
                calendar_method="REQUEST",
            ),
        )
        calendars = [
            part
            for part in message.walk()
            if part.get_content_type() == "text/calendar"
        ]
        self.assertEqual(len(calendars), 1)
        self.assertEqual(calendars[0].get_param("method"), "REQUEST")
        self.assertEqual(message.get_content_type(), "multipart/alternative")

    def test_imap_index_carries_calendar_bodies_into_sync(self) -> None:
        """Prove the provider boundary passes scheduling MIME content to email sync."""
        message = EmailMessage()
        message["From"] = "organizer@example.com"
        message.set_content("Invitation")
        message.add_alternative(
            "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
            subtype="calendar",
            params={"method": "REQUEST"},
        )
        adapter = ImapSmtpAdapter(SimpleNamespace(pk="account"))
        connection = Mock()
        connection.uid.return_value = (
            "OK",
            [(b"1 (UID 42 FLAGS () BODY[])", message.as_bytes())],
        )
        adapter.connect = Mock(return_value=connection)
        indexed = adapter._fetch_email_index("42", mailbox="INBOX")
        self.assertEqual(indexed.calendar_parts[0].method, "REQUEST")


class CalendarSchedulingIntegrationTests(SchedulingFixtures, TestCase):
    """Exercise actual sync and scheduling services with only provider I/O mocked."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Populate application field metadata required for real policy enforcement."""
        call_command("save_application_fields", suppress_output=True, verbosity=0)

    def setUp(self) -> None:
        """Create connected email identities and isolated inbox destinations."""
        super().setUp()
        self.prepare_calendar()

    def _sync_calendar_delivery(self, result: EmailSendResult, *, is_draft: bool = False) -> None:
        """Reconcile a retained outbound identity through the real email persistence boundary."""
        email = BloomerpEmail(
            provider=self.account.provider,
            provider_message_id=result.provider_message_id,
            provider_message_id_scope="account",
            email_account_id=str(self.account.pk),
            mailbox="Drafts" if is_draft else "Sent",
            message_id=result.message_id or "<calendar-confirmed@test>",
            sender=self.account.email_address,
            subject="Calendar delivery",
            is_draft=is_draft,
        )
        for folder in (self.folder, self.second_folder):
            self.index_email(email, folder)

    def test_uncertain_reply_retains_identity_and_resumes_after_sent_sync(self) -> None:
        """Keep attendance unchanged until sync confirms the original reply without resending it."""
        self.index_email(self.make_email())
        event = CalendarEvent.objects.get(calendar_uid=UID)
        result = EmailSendResult(provider_message_id="uncertain-reply")
        adapter = Mock()
        adapter.send_email.side_effect = EmailSendUnconfirmed(result)
        arguments = {
            "user": self.actor, "event_id": event.pk,
            "response_status": "accepted", "expected_sequence": 0,
        }
        locks = Mock()
        preparation_adapter = Mock()
        prepare = Mock()
        provider = SimpleNamespace(
            adapter_class=Mock(return_value=preparation_adapter),
            authorization=SimpleNamespace(prepare=prepare),
        )
        with (
            patch("bloomerp.communication.calendar.outgoing._resolve_email_adapter_for_account", return_value=adapter),
            patch("bloomerp.communication.calendar.outgoing.EMAIL_PROVIDER_REGISTRY.get", return_value=provider),
            patch.object(EmailAccount.objects, "select_for_update", wraps=EmailAccount.objects.select_for_update) as account_lock,
            patch.object(CalendarEvent.objects, "select_for_update", wraps=CalendarEvent.objects.select_for_update) as event_lock,
        ):
            locks.attach_mock(account_lock, "account")
            locks.attach_mock(event_lock, "event")
            locks.attach_mock(prepare, "prepare")
            with self.assertRaises(PermissionDenied):
                respond_to_calendar_invitation(
                    **{**arguments, "user": self.outsider},
                    email_account_id=self.account.pk, inbox_id=self.inbox.pk,
                )
            prepare.assert_not_called()
            with patch("bloomerp.communication.calendar.outgoing._calendar_delivery_account_id", return_value=None), self.assertRaisesMessage(ValidationError, "sending account changed"):
                respond_to_calendar_invitation(**arguments)
            adapter.send_email.assert_not_called()
            locks.reset_mock()
            with self.assertRaisesMessage(ValidationError, "did not confirm delivery"):
                respond_to_calendar_invitation(**arguments)
            self.assertEqual(locks.mock_calls[:3], [call.prepare(preparation_adapter), call.account(), call.event()])
            participant = event.participants.get(email=self.account.email_address)
            self.assertEqual(participant.response_status, "awaiting_response")
            self.assertIsNone(participant.last_sent_reply_sequence)
            pending = InboxItem.objects.filter(raw_meta_data__provider_identity=result.provider_message_id)
            self.assertEqual(pending.count(), 2)
            self.assertTrue(all(item.raw_meta_data["outbound_send_pending"] for item in pending))
            self._sync_calendar_delivery(result, is_draft=True)
            with self.assertRaisesMessage(ValidationError, "did not confirm delivery"):
                respond_to_calendar_invitation(**arguments)
            self._sync_calendar_delivery(result)
            with patch("bloomerp.communication.calendar.outgoing.timezone.now", return_value=STAMP + timedelta(days=20)):
                self.assertEqual(respond_to_calendar_invitation(**arguments), "<calendar-confirmed@test>")
            self.assertIsNone(respond_to_calendar_invitation(**arguments))
        adapter.send_email.assert_called_once()
        participant.refresh_from_db()
        self.assertEqual(participant.response_status, "accepted")
        self.assertEqual(participant.last_sent_reply_sequence, 0)

    def test_uncertain_request_and_nested_cancellation_keep_the_saved_event(self) -> None:
        """Preserve initial and cancellation send guards across their different transaction depths."""
        event = self.local_event()
        request = EmailSendResult(provider_message_id="uncertain-request", message_id="<request@test>")
        cancellation = EmailSendResult(provider_message_id="uncertain-cancel", message_id="<cancel@test>")
        adapter = Mock()
        adapter.send_email.side_effect = [EmailSendUnconfirmed(request), EmailSendUnconfirmed(cancellation)]
        arguments = {"user": self.actor, "event_id": event.pk, "email_account_id": self.account.pk}
        locks = Mock()
        with (
            patch("bloomerp.communication.calendar.outgoing._resolve_email_adapter_for_account", return_value=adapter),
            patch.object(EmailAccount.objects, "select_for_update", wraps=EmailAccount.objects.select_for_update) as account_lock,
            patch.object(CalendarEvent.objects, "select_for_update", wraps=CalendarEvent.objects.select_for_update) as event_lock,
        ):
            locks.attach_mock(account_lock, "account")
            locks.attach_mock(event_lock, "event")
            with patch("bloomerp.communication.calendar.outgoing._attendees", return_value=list(event.participants.order_by("email"))):
                for _attempt in range(2):
                    with self.assertRaisesMessage(ValidationError, "did not confirm delivery"):
                        send_calendar_request(**arguments)
            self.assertEqual(locks.mock_calls[:2], [call.account(), call.event()])
            event.refresh_from_db()
            self.assertIsNone(event.invitation_sent_at)
            self.assertEqual(event.sequence, 0)
            self.assertEqual(adapter.send_email.call_count, 1)
            self._sync_calendar_delivery(request)
            with patch("bloomerp.communication.calendar.outgoing._attendees", return_value=list(event.participants.order_by("-email"))):
                self.assertEqual(send_calendar_request(**arguments), "<request@test>")
            locks.reset_mock()
            for _attempt in range(2):
                with self.assertRaisesMessage(ValidationError, "did not confirm delivery"):
                    cancel_calendar_event(user=self.actor, event_id=event.pk)
            self.assertEqual(locks.mock_calls[:2], [call.account(), call.event()])
            event.refresh_from_db()
            self.assertFalse(event.cancelled)
            self.assertEqual(event.sequence, 0)
            self.assertEqual(InboxItem.objects.filter(
                raw_meta_data__provider_identity=cancellation.provider_message_id,
                raw_meta_data__outbound_send_pending=True,
            ).count(), 2)
            self._sync_calendar_delivery(cancellation)
            cancel_calendar_event(user=self.actor, event_id=event.pk)
        self.assertEqual(adapter.send_email.call_count, 2)
        event.refresh_from_db()
        self.assertTrue(event.cancelled)
        self.assertEqual(event.sequence, 1)

    def test_later_uncertainty_keeps_an_earlier_recipient_cancellation_checkpoint(self) -> None:
        """Resume a partially delivered revision without repeating its successful first message."""
        event = self.local_event()
        event.invitation_sent_at = STAMP
        event.save()
        event.participants.filter(email="first@example.com").update(invitation_cancelled=True)
        cancellation = EmailSendResult(provider_message_id="removed-guest", message_id="<removed@test>")
        update = EmailSendResult(provider_message_id="remaining-guests", message_id="<update@test>")
        adapter = Mock()
        adapter.send_email.side_effect = [cancellation, EmailSendUnconfirmed(update)]
        arguments = {"user": self.actor, "event_id": event.pk, "email_account_id": self.account.pk}
        with patch("bloomerp.communication.calendar.outgoing._resolve_email_adapter_for_account", return_value=adapter):
            with self.assertRaisesMessage(ValidationError, "did not confirm delivery"):
                send_calendar_request(**arguments)
            self.assertTrue(event.participants.filter(email="first@example.com").exists())
            self.assertEqual(InboxItem.objects.filter(
                raw_meta_data__provider_identity=cancellation.provider_message_id,
                raw_meta_data__outbound_send_pending=False,
            ).count(), 2)
            self._sync_calendar_delivery(update)
            self.assertEqual(send_calendar_request(**arguments), "<update@test>")
        self.assertEqual(adapter.send_email.call_count, 2)
        self.assertFalse(event.participants.filter(email="first@example.com").exists())
        event.refresh_from_db()
        self.assertEqual(event.sequence, 1)

    def test_removed_guest_cancellation_is_sent_before_remaining_guest_update(self) -> None:
        """Retain removed recipients until their targeted cancellation succeeds without cancelling everyone."""
        event = self.local_event()
        event.invitation_sent_at = STAMP
        event.save()
        removed = event.participants.get(email="first@example.com")
        removed.invitation_cancelled = True
        removed.save()
        with patch("bloomerp.communication.calendar.outgoing._send", return_value="sent") as send:
            send_calendar_request(user=self.actor, event_id=event.pk, email_account_id=self.account.pk)
        self.assertEqual([call.args[2] for call in send.call_args_list], ["CANCEL", "REQUEST"])
        self.assertEqual(send.call_args_list[0].args[4], ["first@example.com"])
        self.assertEqual(send.call_args_list[1].args[4], ["second@example.com"])
        cancellation = parse_scheduling_message(send.call_args_list[0].args[3].decode())
        self.assertNotIn("STATUS", cancellation.event)
        self.assertEqual(cancellation.sequence, 1)
        self.assertFalse(event.participants.filter(pk=removed.pk).exists())
        event.refresh_from_db()
        self.assertFalse(event.cancelled)

    def test_failed_guest_cancellation_preserves_pending_identity_and_revision(self) -> None:
        """A failed cancellation remains retryable without deleting its recipient or advancing revision."""
        event = self.local_event()
        event.invitation_sent_at = STAMP
        event.save()
        event.participants.filter(email="first@example.com").update(invitation_cancelled=True)
        with patch("bloomerp.communication.calendar.outgoing._send", side_effect=RuntimeError("offline")), self.assertRaises(RuntimeError):
            send_calendar_request(user=self.actor, event_id=event.pk, email_account_id=self.account.pk)
        event.refresh_from_db()
        self.assertEqual(event.sequence, 0)
        self.assertTrue(event.participants.filter(email="first@example.com", invitation_cancelled=True).exists())

    def test_guest_removal_delivery_does_not_require_a_general_update_email(self) -> None:
        """The automatic removal path sends cancellation only, leaving retained guests' responses intact."""
        event = self.local_event()
        event.invitation_sent_at = STAMP
        event.save()
        event.participants.update(response_status="accepted")
        event.participants.filter(email="first@example.com").update(invitation_cancelled=True)
        with patch("bloomerp.communication.calendar.outgoing._send", return_value="sent") as send:
            send_removed_calendar_cancellations(user=self.actor, event_id=event.pk)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[2], "CANCEL")
        self.assertEqual(send.call_args.args[4], ["first@example.com"])
        self.assertEqual(event.participants.get(email="second@example.com").response_status, "accepted")

    def test_cancelling_last_guest_sends_only_a_targeted_cancellation(self) -> None:
        """An organizer left alone can cancel all removed guests without attempting an empty REQUEST."""
        event = self.local_event()
        event.invitation_sent_at = STAMP
        event.save()
        event.participants.update(invitation_cancelled=True)
        with patch("bloomerp.communication.calendar.outgoing._send", return_value="sent") as send:
            send_calendar_request(user=self.actor, event_id=event.pk, email_account_id=self.account.pk)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[2], "CANCEL")
        self.assertFalse(event.participants.exists())

    def test_cancel_event_delivers_before_marking_cancelled_and_is_idempotent(self) -> None:
        """Cancellation uses the original connected sender and preserves the event on provider failure."""
        event = self.local_event()
        event.invitation_sent_at = STAMP
        event.save()
        with patch("bloomerp.communication.calendar.outgoing._send", side_effect=RuntimeError("offline")), self.assertRaises(RuntimeError):
            cancel_calendar_event(user=self.actor, event_id=event.pk)
        event.refresh_from_db()
        self.assertFalse(event.cancelled)
        with patch("bloomerp.communication.calendar.outgoing._send", return_value="sent") as send:
            cancel_calendar_event(user=self.actor, event_id=event.pk)
            cancel_calendar_event(user=self.actor, event_id=event.pk)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[2], "CANCEL")
        cancellation = parse_scheduling_message(send.call_args.args[3].decode())
        self.assertEqual(str(cancellation.event["STATUS"]), "CANCELLED")
        event.refresh_from_db()
        self.assertTrue(event.cancelled)

    def test_local_email_only_invitee_can_resolve_their_connected_mailbox(self) -> None:
        """Resolve local invitees without requiring provider authorization for an attendance update."""
        event = self.local_event()
        participant = event.participants.create(email=self.account.email_address)
        self.assertEqual(event.get_participant(self.actor).pk, participant.pk)
        self.assertIsNone(event.get_participant(self.outsider))
        self.assertIsNone(event.get_participant(self.owner))
        with patch(
            "bloomerp.communication.calendar.outgoing._prepare_calendar_authorization",
            side_effect=AssertionError("A local response must not refresh remote credentials."),
        ):
            self.assertIsNone(respond_to_calendar_invitation(
                user=self.actor, event_id=event.pk, response_status="accepted", expected_sequence=0,
            ))
        participant.refresh_from_db()
        self.assertEqual(participant.response_status, "accepted")

    def test_event_can_be_cancelled_after_all_guest_removals_were_delivered(self) -> None:
        """Cancel the remaining local record when all formerly emailed guests have already been removed."""
        event = self.local_event()
        event.invitation_sent_at = STAMP
        event.save()
        event.participants.all().delete()
        with (
            patch("bloomerp.communication.calendar.outgoing._send") as send,
            patch(
                "bloomerp.communication.calendar.outgoing._prepare_calendar_authorization",
                side_effect=AssertionError("A local cancellation must not refresh remote credentials."),
            ),
        ):
            cancel_calendar_event(user=self.actor, event_id=event.pk)
            cancel_calendar_event(user=self.actor, event_id=event.pk)
        send.assert_not_called()
        event.refresh_from_db()
        self.assertTrue(event.cancelled)

    def test_attendee_cancellation_removes_only_cancelled_recipient_placements(self) -> None:
        """Remove a cancelled mailbox's Inbox placement while retaining another invited mailbox's placement."""
        self.index_email(self.make_email())
        event = CalendarEvent.objects.get(calendar_uid=UID)
        other_account = EmailAccount.objects.create(email_address="other@example.com", status="active")
        self.second_folder.related_object_id = str(other_account.pk)
        self.second_folder.save()
        event.inboxes.add(self.team)
        self.index_email(self.make_email("CANCEL", sequence=1, attendees=(self.account.email_address,)))
        event.refresh_from_db()
        self.assertFalse(event.cancelled)
        self.assertFalse(event.inboxes.filter(pk=self.inbox.pk).exists())
        self.assertTrue(event.inboxes.filter(pk=self.team.pk).exists())

    def test_attendee_cancellation_does_not_consume_a_shared_event_update_revision(self) -> None:
        """A removed guest's CANCEL arriving first must not suppress the same revision's remaining-guest REQUEST."""
        self.index_email(self.make_email())
        event = CalendarEvent.objects.get(calendar_uid=UID)
        self.index_email(self.make_email("CANCEL", sequence=1, attendees=(self.account.email_address,)))
        other_account = EmailAccount.objects.create(email_address="other@example.com", status="active")
        self.second_folder.related_object_id = str(other_account.pk)
        self.second_folder.save()
        self.account = other_account
        self.index_email(self.make_email(sequence=1, attendees=("other@example.com",)), self.second_folder)
        event.refresh_from_db()
        self.assertEqual(event.sequence, 1)
        self.assertEqual(event.start.hour, 13)
        self.assertTrue(event.participants.get(email="owner@example.com").invitation_cancelled)
        self.assertFalse(event.cancelled)

    def test_account_sync_creates_one_pending_event_in_multiple_inboxes(self) -> None:
        """Use the account sync path to create one shared event and explicit attendees."""
        email = self.make_email()
        with patch(
            "bloomerp.communication.builtins.emails.sync._resolve_email_adapter_for_account"
        ) as resolve:
            resolve.return_value.sync_emails.return_value = [email]
            handle_email_account_sync(
                InboxFolder.objects.filter(
                    pk__in=[self.folder.pk, self.second_folder.pk]
                ),
                email_account_id=str(self.account.pk),
            )
        event = CalendarEvent.objects.get(calendar_uid=UID)
        self.assertEqual(event.inboxes.count(), 2)
        self.assertIsNone(event.organizing_inbox_id)
        self.assertEqual(event.participants.count(), 2)
        self.assertEqual(
            event.participants.get(email=self.account.email_address).user_id,
            self.owner.pk,
        )
        self.assertEqual(
            set(event.participants.values_list("response_status", flat=True)),
            {"awaiting_response"},
        )
        self.index_email(email)
        self.assertEqual(CalendarEvent.objects.count(), 1)
        self.assertEqual(event.participants.count(), 2)

    def test_newer_request_updates_shared_event_and_older_request_does_not_roll_back(
        self,
    ) -> None:
        """Apply revisions in place and ignore stale or repeated invitation delivery."""
        self.index_email(self.make_email())
        event = CalendarEvent.objects.get(calendar_uid=UID)
        participant = event.participants.get(email=self.account.email_address)
        participant.response_status = "accepted"
        participant.save()
        self.index_email(self.make_email())
        participant.refresh_from_db()
        self.assertEqual(participant.response_status, "accepted")
        self.index_email(self.make_email(sequence=1))
        event.refresh_from_db()
        participant.refresh_from_db()
        self.assertEqual(event.title, "Planning revision 1")
        self.assertEqual(event.start.hour, 13)
        self.assertEqual(participant.response_status, "awaiting_response")
        stale_item = self.index_email(self.make_email())
        event.refresh_from_db()
        self.assertEqual(event.sequence, 1)
        self.assertNotIn("event_id", stale_item.raw_meta_data["calendar_processing"][0])

    def test_reply_requires_existing_attendee_sender_and_current_revision(self) -> None:
        """Accept a valid reply while rejecting mismatched identities and stale responses."""
        event = self.local_event()
        reply = self.make_email(
            "REPLY",
            organizer=self.account.email_address,
            attendees=("first@example.com",),
        )
        self.index_email(reply)
        participant = event.participants.get(email="first@example.com")
        self.assertEqual(participant.response_status, "accepted")
        self.assertEqual(participant.responded_at, STAMP)
        self.index_email(
            self.make_email(
                "REPLY",
                organizer=self.account.email_address,
                attendees=("first@example.com",),
                status="DECLINED",
                seconds=1,
            )
        )
        participant.refresh_from_db()
        self.assertEqual(participant.response_status, "declined")
        self.index_email(reply)
        participant.refresh_from_db()
        self.assertEqual(participant.response_status, "declined")
        spoof = self.make_email(
            "REPLY",
            organizer=self.account.email_address,
            attendees=("first@example.com",),
            sender="intruder@example.com",
            seconds=2,
        )
        item = self.index_email(spoof)
        self.assertNotIn("event_id", item.raw_meta_data["calendar_processing"][0])
        unmatched = self.index_email(
            self.make_email(
                "REPLY",
                organizer=self.account.email_address,
                attendees=("unknown@example.com",),
                seconds=3,
            )
        )
        self.assertNotIn("event_id", unmatched.raw_meta_data["calendar_processing"][0])
        event.sequence = 1
        event.save()
        self.index_email(reply)
        self.assertEqual(event.participants.count(), 2)

    def test_cancel_before_request_keeps_a_revision_tombstone(self) -> None:
        """An earlier invitation cannot resurrect a cancellation synced first."""
        self.index_email(self.make_email("CANCEL", sequence=1, attendees=()))
        self.assertEqual(CalendarSchedulingCancellation.objects.count(), 1)
        self.assertFalse(CalendarEvent.objects.exists())
        self.index_email(self.make_email())
        self.assertFalse(CalendarEvent.objects.exists())
        self.index_email(self.make_email(sequence=2))
        self.assertTrue(CalendarEvent.objects.exists())

    def test_whole_and_attendee_cancellation_are_distinct(self) -> None:
        """Cancelling one attendee must not cancel the shared meeting for everyone."""
        self.index_email(self.make_email())
        event = CalendarEvent.objects.get(calendar_uid=UID)
        self.index_email(
            self.make_email(
                "CANCEL", sequence=1, attendees=(self.account.email_address,)
            )
        )
        event.refresh_from_db()
        self.assertFalse(event.cancelled)
        self.assertTrue(
            event.participants.get(
                email=self.account.email_address
            ).invitation_cancelled
        )
        self.assertFalse(
            event.participants.get(email="other@example.com").invitation_cancelled
        )
        self.index_email(self.make_email("CANCEL", sequence=2, attendees=()))
        event.refresh_from_db()
        self.assertTrue(event.cancelled)
        self.index_email(self.make_email())
        event.refresh_from_db()
        self.assertTrue(event.cancelled)

    def test_all_day_ranges_are_preserved_and_unsupported_content_does_not_abort_indexing(
        self,
    ) -> None:
        """Preserve date semantics while isolating malformed and recurring scheduling content."""
        item = self.index_email(self.make_email(all_day=True))
        event = CalendarEvent.objects.get(calendar_uid=UID)
        self.assertTrue(event.all_day)
        self.assertIsNone(event.start)
        self.assertEqual((event.end_date - event.start_date).days, 2)
        self.index_email(self.make_email(recurring=True, sequence=1))
        event.refresh_from_db()
        self.assertEqual(event.sequence, 0)
        malformed = self.make_email(sequence=2)
        malformed.calendar_parts[0].content = "not a calendar"
        item = self.index_email(malformed)
        self.assertEqual(
            item.raw_meta_data["calendar_processing"][0]["outcome"], "requires_review"
        )

    def test_plain_calendar_export_is_not_automatically_a_scheduling_request(
        self,
    ) -> None:
        """Require METHOD instead of treating every calendar file as an invitation."""
        email = self.make_email()
        email.calendar_parts[0].content = email.calendar_parts[0].content.replace(
            "METHOD:REQUEST\r\n", ""
        )
        self.index_email(email)
        self.assertFalse(CalendarEvent.objects.exists())

    def test_reply_service_records_and_sends_one_structured_response(self) -> None:
        """An app response updates the same attendee and sends one standard reply."""
        self.index_email(self.make_email())
        event = CalendarEvent.objects.get(calendar_uid=UID)
        with patch(
            "bloomerp.communication.calendar.outgoing._send",
            return_value="<reply@test>",
        ) as send:
            for _ in range(2):
                respond_to_calendar_invitation(
                    user=self.actor,
                    event_id=event.pk,
                    email_account_id=self.account.pk,
                    inbox_id=self.inbox.pk,
                    response_status="accepted",
                    expected_sequence=0,
                )
        self.assertEqual(send.call_count, 1)
        message = parse_scheduling_message(send.call_args.args[3].decode(), "REPLY")
        self.assertEqual(
            message.attendees[0][:2], (self.account.email_address, "accepted")
        )
        self.assertEqual(
            event.participants.get(email=self.account.email_address).response_status,
            "accepted",
        )
        self.assertEqual(event.participants.count(), 2)

    def test_organizer_invitation_update_and_cancellation_keep_the_same_uid(
        self,
    ) -> None:
        """Send invitations, updates, and cancellation through ordinary multi-recipient mail."""
        event = self.local_event()
        with patch(
            "bloomerp.communication.calendar.outgoing._send", return_value="<sent@test>"
        ) as send:
            send_calendar_request(
                user=self.actor, event_id=event.pk, email_account_id=self.account.pk
            )
            self.assertEqual(send.call_count, 1)
            self.assertEqual(
                set(send.call_args.args[4]),
                {"first@example.com", "second@example.com"},
            )
            event.refresh_from_db()
            event.start += timedelta(hours=1)
            event.end += timedelta(hours=1)
            event.save()
            event.participants.update(response_status="accepted")
            send_calendar_request(
                user=self.actor, event_id=event.pk, email_account_id=self.account.pk
            )
            event.refresh_from_db()
            self.assertEqual(event.sequence, 1)
            send_calendar_request(
                user=self.actor,
                event_id=event.pk,
                email_account_id=self.account.pk,
                cancel=True,
            )
        event.refresh_from_db()
        self.assertEqual(event.sequence, 2)
        self.assertTrue(event.cancelled)
        messages = [
            parse_scheduling_message(call.args[3].decode())
            for call in send.call_args_list
        ]
        self.assertEqual(
            [message.method for message in messages], ["REQUEST", "REQUEST", "CANCEL"]
        )
        self.assertEqual([message.sequence for message in messages], [0, 1, 2])
        self.assertEqual(
            {attendee[1] for attendee in messages[1].attendees}, {"awaiting_response"}
        )
        self.assertIn(b"RSVP=TRUE", send.call_args_list[1].args[3])
        self.assertEqual({message.uid for message in messages}, {UID})

    def test_failed_send_does_not_record_a_successful_calendar_revision(self) -> None:
        """Propagate ordinary email failures without advancing event or RSVP state."""
        event = self.local_event()
        with patch(
            "bloomerp.communication.calendar.outgoing._send", return_value="<sent@test>"
        ):
            send_calendar_request(
                user=self.actor, event_id=event.pk, email_account_id=self.account.pk
            )
        event.refresh_from_db()
        sent_at = event.invitation_sent_at
        event.participants.update(response_status="accepted")
        for cancel in (False, True):
            with (
                self.subTest(cancel=cancel),
                patch(
                    "bloomerp.communication.calendar.outgoing._send",
                    side_effect=ValidationError("Email could not be sent"),
                ) as send,
                self.assertRaisesMessage(ValidationError, "Email could not be sent"),
            ):
                send_calendar_request(
                    user=self.actor,
                    event_id=event.pk,
                    email_account_id=self.account.pk,
                    cancel=cancel,
                )
            self.assertEqual(send.call_count, 1)
            event.refresh_from_db()
            self.assertEqual(event.sequence, 0)
            self.assertEqual(event.invitation_sent_at, sent_at)
            self.assertFalse(event.cancelled)
            self.assertEqual(
                set(event.participants.values_list("response_status", flat=True)),
                {"accepted"},
            )

    def test_failed_reply_does_not_record_a_successful_response(self) -> None:
        """Leave attendance unchanged when ordinary email sending rejects the reply."""
        self.index_email(self.make_email())
        event = CalendarEvent.objects.get(calendar_uid=UID)
        with (
            patch(
                "bloomerp.communication.calendar.outgoing._send",
                side_effect=ValidationError("Reply could not be sent"),
            ) as send,
            self.assertRaisesMessage(ValidationError, "Reply could not be sent"),
        ):
            respond_to_calendar_invitation(
                user=self.actor,
                event_id=event.pk,
                email_account_id=self.account.pk,
                inbox_id=self.inbox.pk,
                response_status="accepted",
                expected_sequence=0,
            )
        self.assertEqual(send.call_count, 1)
        participant = event.participants.get(email=self.account.email_address)
        self.assertEqual(participant.response_status, "awaiting_response")
        self.assertIsNone(participant.last_sent_reply_sequence)
        self.assertEqual(participant.last_sent_reply_status, "")

    def test_email_access_alone_does_not_authorize_calendar_writes(self) -> None:
        """An Inbox owner with no calendar policy cannot send or mutate attendance."""
        event = self.local_event()
        with self.assertRaises(PermissionDenied):
            send_calendar_request(
                user=self.owner, event_id=event.pk, email_account_id=self.account.pk
            )

    def test_imported_meeting_cannot_be_rescheduled_by_generic_local_save(self) -> None:
        """Keep external organizer authority separate from local calendar placement."""
        self.index_email(self.make_email())
        event = CalendarEvent.objects.get(calendar_uid=UID)
        event.start += timedelta(hours=1)
        event.end += timedelta(hours=1)
        with self.assertRaises(ValidationError):
            event.save()
        event.refresh_from_db()
        event.inboxes.add(self.team)
        self.assertEqual(event.inboxes.count(), 2)

    def test_internal_invitation_reuses_local_shared_event(self) -> None:
        """Receiving a local organizer's invitation adds placement without an event clone."""
        event = self.local_event()
        event.participants.create(email=self.account.email_address, user=self.owner)
        event.inboxes.remove(self.team)
        with patch(
            "bloomerp.communication.calendar.outgoing._send", return_value="<sent@test>"
        ) as send:
            send_calendar_request(
                user=self.actor, event_id=event.pk, email_account_id=self.account.pk
            )
        payload = send.call_args.args[3].decode()
        email = self.make_email(organizer=self.account.email_address)
        email.sender = self.account.email_address
        email.calendar_parts[0].content = payload
        item = self.index_email(email, self.second_folder)
        self.assertEqual(CalendarEvent.objects.count(), 1)
        self.assertEqual(event.inboxes.count(), 2)
        self.assertEqual(
            item.raw_meta_data["calendar_processing"][0]["outcome"], "local_invitation"
        )

    def test_unknown_recipient_and_spoofed_request_do_not_link_private_events(
        self,
    ) -> None:
        """Do not attach existing event identities to unrelated inbox messages."""
        self.index_email(self.make_email())
        wrong = self.make_email(sequence=1, attendees=("unrelated@example.com",))
        item = self.index_email(wrong)
        self.assertNotIn("event_id", item.raw_meta_data["calendar_processing"][0])
        spoof = self.make_email(sequence=1, sender="intruder@example.com")
        item = self.index_email(spoof)
        self.assertNotIn("event_id", item.raw_meta_data["calendar_processing"][0])
        self.assertEqual(CalendarEvent.objects.get().sequence, 0)

    def test_custom_source_timezone_definition_is_resolved_and_retained(self) -> None:
        """Resolve supplied VTIMEZONE data and preserve custom source timezone semantics."""
        email = self.make_email()
        email.calendar_parts[0].content = "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//Test//EN",
                "METHOD:REQUEST",
                "BEGIN:VTIMEZONE",
                "TZID:Custom/Office",
                "BEGIN:STANDARD",
                "DTSTART:19700101T000000",
                "TZOFFSETFROM:+0230",
                "TZOFFSETTO:+0230",
                "END:STANDARD",
                "END:VTIMEZONE",
                "BEGIN:VEVENT",
                f"UID:{UID}",
                "DTSTAMP:20260101T000000Z",
                "ORGANIZER:mailto:organizer@example.com",
                "ATTENDEE:mailto:owner@example.com",
                "SUMMARY:Custom timezone meeting",
                "DTSTART;TZID=Custom/Office:20261015T143000",
                "DTEND;TZID=Custom/Office:20261015T153000",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        )
        self.index_email(email)
        event = CalendarEvent.objects.get()
        self.assertEqual(event.start.hour, 12)
        self.assertEqual(event.start.minute, 0)
        self.assertIn("TZID:Custom/Office", event.source_calendar)

    def test_floating_times_and_mismatched_mime_method_require_review(self) -> None:
        """Do not guess a timezone or apply a payload whose METHOD conflicts with MIME."""
        email = self.make_email()
        email.calendar_parts[0].content = (
            email.calendar_parts[0]
            .content.replace("20261015T120000Z", "20261015T120000")
            .replace("20261015T130000Z", "20261015T130000")
        )
        item = self.index_email(email)
        self.assertEqual(
            item.raw_meta_data["calendar_processing"][0]["outcome"], "requires_review"
        )
        self.assertFalse(CalendarEvent.objects.exists())
        email = self.make_email(sequence=1)
        email.calendar_parts[0].method = "CANCEL"
        self.index_email(email)
        self.assertFalse(CalendarEvent.objects.exists())

    def test_attendee_tombstone_survives_import_through_another_account(self) -> None:
        """Do not resurrect a removed attendee when another invitee imports an older request."""
        self.index_email(
            self.make_email(
                "CANCEL", sequence=1, attendees=(self.account.email_address,)
            )
        )
        other_account = EmailAccount.objects.create(
            email_address="other@example.com", status="active"
        )
        other_folder = InboxFolder.objects.create(
            inbox=self.team, type="email", related_object_id=str(other_account.pk)
        )
        email = self.make_email()
        email.email_account_id = str(other_account.pk)
        email.to = [other_account.email_address]
        self.index_email(email, other_folder)
        event = CalendarEvent.objects.get()
        self.assertTrue(
            event.participants.get(
                email=self.account.email_address
            ).invitation_cancelled
        )
        self.assertFalse(
            event.participants.get(
                email=other_account.email_address
            ).invitation_cancelled
        )
        self.assertEqual(event.inboxes.count(), 1)
