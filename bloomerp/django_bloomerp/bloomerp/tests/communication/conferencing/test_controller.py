"""Cross-model call workflows that exceed a single model lifecycle scenario."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import OperationalError
from django.http import Http404
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import override

from bloomerp.communication.builtins.conferencing.controller import (
    ConferenceController,
    ConferenceUnavailable,
    publish_session,
)
from bloomerp.communication.builtins.conferencing.webhooks import reconcile_event
from bloomerp.communication.builtins.instant_messaging.calling import start_call
from bloomerp.communication.builtins.instant_messaging.registry import (
    IM_PROVIDER_REGISTRY,
)
from bloomerp.models.communication.conferencing import (
    ConferenceAttendance,
    ConferenceRoom,
    ConferenceSession,
    ConferenceWebhookReceipt,
)
from bloomerp.models.communication.instant_messaging import IMConversationActivity
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels

from .fixtures import CallFixtures


class TestConferenceController(CallFixtures, BaseBloomerpTestCaseWithModels):
    """Verify retries, event ordering, admission and provider-driven projections."""

    def test_solo_meeting_join_and_webhook(self) -> None:
        """Join a room without a conversation and persist its provider attendance."""
        self.prepare_call()
        room = ConferenceRoom.objects.create(
            title="Solo meeting", created_by=self.normal_user
        )
        controller = ConferenceController(self.normal_user)
        self.session = controller.start(
            room, [self.normal_user], "video", "solo-meeting"
        )
        credentials = controller.join(self.session.pk)
        self.assertEqual(credentials["driver"], "livekit")
        self.assertEqual(credentials["can_end"], "true")
        reconcile_event(
            self.connection_event(
                "EV_solo_join", "participant_joined", credentials["identity"]
            )
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "active")
        self.assertEqual(
            ConferenceAttendance.objects.get().participant.user_id,
            self.normal_user.pk,
        )
        self.assertEqual(
            ConferenceWebhookReceipt.objects.get(event_id="EV_solo_join").status,
            "processed",
        )

    def test_projection_failure_does_not_fail_start_response(self) -> None:
        """A failed post-commit projection must not turn a durable call into HTTP 500."""
        self.prepare_call()
        client = Client()
        client.force_login(self.normal_user)
        with (
            patch(
                "bloomerp.communication.builtins.conferencing.im.project_session",
                side_effect=OperationalError("database is locked"),
            ),
            self.assertLogs("django.db.backends.base", level="ERROR"),
        ):
            response = client.post(
                reverse(
                    "components_im_start_call", kwargs={"conversation_id": self.chat.pk}
                ),
                {
                    "media_mode": "video",
                    "client_id": "commit-callback-failure",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ConferenceSession.objects.get().status, "ringing")
        joined = client.post(response.json()["join_url"])
        self.assertEqual(joined.status_code, 200)

    def test_projection_retries_sqlite_lock_without_duplicate_activity(self) -> None:
        """Retry a rolled-back SQLite projection and preserve one timeline activity."""
        from bloomerp.communication.builtins.conferencing.im import (
            project_session,
            store_session_activity,
        )

        self.prepare_session()
        attempts = 0

        def fail_then_store(session_id: UUID) -> bool:
            """Simulate a transient write lock before allowing the real projection."""
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OperationalError("database is locked")
            return store_session_activity(session_id)

        with (
            patch(
                "bloomerp.communication.builtins.conferencing.im.connection.vendor",
                "sqlite",
            ),
            patch(
                "bloomerp.communication.builtins.conferencing.im.store_session_activity",
                side_effect=fail_then_store,
            ),
            patch("bloomerp.communication.builtins.conferencing.im.sleep") as pause,
        ):
            project_session(self.session)
        self.assertEqual(attempts, 2)
        pause.assert_called_once_with(0.05)
        self.assertEqual(
            IMConversationActivity.objects.filter(
                source_id=str(self.session.pk)
            ).count(),
            1,
        )

    def test_uncertain_start_reuses_reservation(self) -> None:
        """Use case: Start times out. Expected result: retry provisions the same reserved media room."""
        # 1. Fail the first request after the local reservation has been persisted.
        self.prepare_call()
        self.create_room.side_effect = TimeoutError
        with self.assertRaises(ConferenceUnavailable):
            start_call(self.normal_user, self.chat.pk, "video", "stable-request")
        reserved = ConferenceSession.objects.get()
        self.assertEqual(reserved.status, "pending")
        # 2. Retry with the same identifier and verify that no call is duplicated.
        self.create_room.side_effect = None
        result = start_call(self.normal_user, self.chat.pk, "video", "stable-request")
        self.assertEqual(result["session_id"], str(reserved.pk))
        self.assertEqual(ConferenceSession.objects.count(), 1)
        self.assertEqual(self.create_room.call_args.args[0], reserved.livekit_room_name)

    def test_replay_out_of_order_leave_and_full_reconnection(self) -> None:
        """Use case: Duplicate/reordered events and reconnect. Expected result: durable nonoverwritten intervals."""
        # 1. Receive a leave before its corresponding join and replay both events.
        self.prepare_session()
        identity = ConferenceController(self.normal_user).join(self.session.pk)[
            "identity"
        ]
        left = self.connection_event("EV_left", "participant_left", identity, offset=2)
        joined = self.connection_event("EV_joined", "participant_joined", identity)
        reconcile_event(left)
        reconcile_event(joined)
        reconcile_event(joined)
        first = ConferenceAttendance.objects.get()
        self.assertIsNotNone(first.left_at)
        self.assertEqual(ConferenceWebhookReceipt.objects.count(), 2)
        # 2. A full reconnect uses the same identity but a new provider SID.
        reconnect = self.connection_event(
            "EV_reconnect", "participant_joined", identity, sid="PA_reconnect", offset=3
        )
        reconcile_event(reconnect)
        self.assertEqual(ConferenceAttendance.objects.count(), 2)
        self.assertEqual(
            ConferenceAttendance.objects.filter(left_at__isnull=True).count(), 1
        )

    def test_finished_session_never_reopens(self) -> None:
        """Use case: Late joins after closure. Expected result: terminal state and media cleanup persist."""
        # 1. Establish an attendance then finish the provider room.
        self.prepare_session()
        identity = ConferenceController(self.normal_user).join(self.session.pk)[
            "identity"
        ]
        reconcile_event(
            self.connection_event("EV_join", "participant_joined", identity)
        )
        reconcile_event(
            self.connection_event("EV_finished", "room_finished", identity, offset=5)
        )
        # 2. Deliver a late join; its token cannot reopen local session state.
        reconcile_event(
            self.connection_event("EV_late", "participant_joined", identity, offset=6)
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "ended")
        self.assertFalse(
            ConferenceAttendance.objects.filter(left_at__isnull=True).exists()
        )
        self.delete_room.assert_awaited_once()

    def test_invalid_or_revoked_connection_is_removed(self) -> None:
        """Use case: Invalid identity or revoked access. Expected result: media removal without attendance."""
        # 1. Reject a provider participant that lacks a server-issued identity.
        self.prepare_session()
        reconcile_event(
            self.connection_event("EV_forged", "participant_joined", "forged")
        )
        self.assertFalse(ConferenceAttendance.objects.exists())
        # 2. Issue a valid token, then revoke eligibility before it is used.
        identity = ConferenceController(self.normal_user).join(self.session.pk)[
            "identity"
        ]
        self.member.left_at = timezone.now()
        self.member.save()
        reconcile_event(
            self.connection_event("EV_revoked", "participant_joined", identity)
        )
        self.assertEqual(self.remove_participant.await_count, 2)
        self.assertFalse(ConferenceAttendance.objects.exists())
        with self.assertRaises(PermissionDenied):
            ConferenceController(self.normal_user).join(self.session.pk)

    def test_receipt_rolls_back_after_failed_cleanup(self) -> None:
        """Use case: Cleanup fails during webhook. Expected result: delivery can be retried successfully."""
        # 1. Close the session and deliver a stale-token recreation event.
        self.prepare_session()
        ConferenceController(self.normal_user).end(self.session.pk)
        event = self.connection_event("EV_recreated", "room_started", "")
        event.room.sid = "RM_recreated"
        self.delete_room.side_effect = TimeoutError
        with self.assertRaises(ConferenceUnavailable):
            reconcile_event(event)
        self.assertFalse(
            ConferenceWebhookReceipt.objects.filter(event_id=event.id).exists()
        )
        # 2. Retry after transport recovery; the event can now be acknowledged.
        self.delete_room.side_effect = None
        reconcile_event(event)
        self.assertTrue(
            ConferenceWebhookReceipt.objects.filter(event_id=event.id).exists()
        )

    def test_end_webhook_does_not_repeat_inbox_alert(self) -> None:
        """Host ending and subsequent webhooks must alert once for the same status."""
        self.prepare_session()
        identity = ConferenceController(self.normal_user).join(self.session.pk)[
            "identity"
        ]
        reconcile_event(
            self.connection_event("EV_active", "participant_joined", identity)
        )
        with patch(
            "bloomerp.communication.builtins.instant_messaging.inbox_source.publish_conversation_activity"
        ) as publish:
            with override("nl"):
                ConferenceController(self.normal_user).end(self.session.pk)
            with override("en"):
                reconcile_event(
                    self.connection_event("EV_finished", "room_finished", "", offset=2)
                )
                reconcile_event(
                    self.connection_event(
                        "EV_finished_again", "room_finished", "", offset=3
                    )
                )
        self.assertEqual(
            [call.kwargs["notify"] for call in publish.call_args_list],
            [True, False, False],
        )
        self.assertEqual(
            IMConversationActivity.objects.filter(
                source_id=str(self.session.pk)
            ).count(),
            1,
        )

    def test_projection_uses_declared_provider_hook(self) -> None:
        """Use case: Publish committed call state. Expected result: one provider-projected timeline activity."""
        # 1. Publish through the provider's configured projection hook.
        self.prepare_session()
        publish_session(self.session.pk)
        publish_session(self.session.pk)
        # 2. Verify idempotent projection into the existing activity index.
        self.assertEqual(
            IMConversationActivity.objects.filter(
                kind="conference_call", source_id=str(self.session.pk)
            ).count(),
            1,
        )
        original = IM_PROVIDER_REGISTRY.get(self.chat.provider_key)
        callback = self.enterContext(
            patch("bloomerp.communication.builtins.conferencing.im.project_session")
        )
        provider = replace(
            original,
            calling=replace(original.calling, session_changed_handler=callback),
        )
        with patch.dict(IM_PROVIDER_REGISTRY._registry, {"INTERNAL": provider}):
            publish_session(self.session.pk)
        callback.assert_called_once()

    def test_browser_mutations_require_csrf(self) -> None:
        """Use case: Cross-site POST. Expected result: all browser mutation endpoints reject it."""
        # 1. Authenticate a client with CSRF enforcement enabled.
        self.prepare_session()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.normal_user)
        # 2. Reject start, join and end requests lacking a CSRF token.
        for name, kwargs in [
            ("components_im_start_call", {"conversation_id": self.chat.pk}),
            ("components_conferencing_join", {"session_id": self.session.pk}),
            ("components_conferencing_end", {"session_id": self.session.pk}),
        ]:
            with self.subTest(route=name):
                self.assertEqual(
                    client.post(reverse(name, kwargs=kwargs), {}).status_code, 403
                )

    def test_revoked_members_do_not_receive_call_notifications(self) -> None:
        """Use case: Member leaves chat. Expected result: later call events reach only eligible invitees."""
        # 1. Preserve the historical invitation but revoke current membership.
        self.prepare_session()
        self.member.left_at = timezone.now()
        self.member.save()
        # 2. Capture the channel boundary and verify the recipient group.
        from unittest.mock import AsyncMock, MagicMock

        layer = MagicMock()
        layer.group_send = AsyncMock()
        with patch("channels.layers.get_channel_layer", return_value=layer):
            publish_session(self.session.pk)
        groups = [call.args[0] for call in layer.group_send.call_args_list]
        self.assertNotIn(f"user_{self.normal_user.pk}", groups)
        self.assertIn(f"user_{self.admin_user.pk}", groups)

    def test_calendar_meeting_reserves_a_link_until_the_host_joins(self) -> None:
        """Keep future links valid without media provisioning, then start once the host explicitly joins."""
        from bloomerp.communication.builtins.conferencing.sharing import shared_session
        from bloomerp.models.communication.calendar import CalendarEvent
        from bloomerp.services.calendar_conferencing import reserve_calendar_conference

        self.prepare_call()
        start = timezone.now() + timedelta(days=2)
        event = CalendarEvent.objects.create(
            title="Future calendar meeting",
            organizer_email="host@example.com",
            start=start,
            end=start + timedelta(hours=1),
            event_timezone="UTC",
        )
        event.participants.create(user=self.admin_user)
        link = reserve_calendar_conference(
            event, self.normal_user, [self.admin_user], "https://app.example/"
        )
        event.refresh_from_db()
        session = event.conference_session
        self.assertEqual(session.status, "pending")
        self.assertIn(str(session.share_token), link)
        self.assertEqual(shared_session(session.share_token).pk, session.pk)
        self.create_room.assert_not_called()
        host_client = Client()
        host_client.force_login(self.normal_user)
        lobby = host_client.get(link.replace("https://app.example", ""))
        self.assertContains(lobby, "Start meeting")
        with self.assertRaises(ValidationError):
            ConferenceController(self.admin_user).join(session.pk)
        self.create_room.assert_not_called()
        guest = Client()
        queued = guest.post(
            reverse(
                "components_conferencing_request_admission",
                kwargs={"token": session.share_token},
            ),
            {"name": "Early visitor"},
        )
        self.assertEqual(queued.status_code, 200)
        self.assertEqual(session.admissions.get().status, "waiting")
        self.create_room.assert_not_called()
        self.create_room.side_effect = RuntimeError("Media provider unavailable")
        unavailable = host_client.post(
            reverse("components_conferencing_join", kwargs={"session_id": session.pk})
        )
        self.assertEqual(unavailable.status_code, 503)
        session.refresh_from_db()
        self.assertEqual(session.status, "pending")
        self.create_room.reset_mock(side_effect=True)
        credentials = ConferenceController(self.normal_user).join(session.pk)
        session.refresh_from_db()
        self.assertEqual(session.status, "ringing")
        self.assertEqual(credentials["can_end"], "true")
        self.create_room.assert_called_once()
        ConferenceController(self.normal_user).join(session.pk)
        self.create_room.assert_called_once()
        event.participants.all().delete()
        with self.assertRaises(PermissionDenied):
            ConferenceController(self.admin_user).join(session.pk)
        event.cancelled = True
        event.save()
        with self.assertRaises(Http404):
            shared_session(session.share_token)
