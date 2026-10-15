"""Shared controller and endpoint fixtures with real authorization and mocked transport."""

from unittest.mock import AsyncMock, patch

from django.test import override_settings
from django.utils import timezone
from livekit import api

from bloomerp.communication.builtins.conferencing.controller import ConferenceController
from bloomerp.communication.builtins.instant_messaging.calling import start_call
from bloomerp.models.communication.conferencing import ConferenceSession
from bloomerp.models.communication.instant_messaging import (
    IMConversation,
    IMConversationParticipant,
)
from bloomerp.tests.base import RequestScenario

from .test_configuration import conferencing_config


class CallFixtures:
    """Build a conversation and scope the external media client to a test double."""

    def prepare_call(self, scenario: RequestScenario | None = None) -> None:
        """Configure active members and return real signed join tokens without networking."""
        self.enterContext(override_settings(BLOOMERP_CONFIG=conferencing_config()))
        self.normal_user.is_staff = True
        self.normal_user.save()
        self.chat = IMConversation.objects.create(name="Team call")
        self.member = IMConversationParticipant.objects.create(
            conversation=self.chat, user=self.normal_user
        )
        self.peer = IMConversationParticipant.objects.create(
            conversation=self.chat, user=self.admin_user
        )
        self.create_room = self.enterContext(
            patch(
                "bloomerp.communication.builtins.conferencing.livekit.LiveKitClient.create_room",
                new_callable=AsyncMock,
            )
        )
        self.create_room.return_value = api.Room(sid="RM_test")
        self.delete_room = self.enterContext(
            patch(
                "bloomerp.communication.builtins.conferencing.livekit.LiveKitClient.delete_room",
                new_callable=AsyncMock,
            )
        )
        self.remove_participant = self.enterContext(
            patch(
                "bloomerp.communication.builtins.conferencing.livekit.LiveKitClient.remove_participant",
                new_callable=AsyncMock,
            )
        )
        if scenario is not None:
            scenario.view_kwargs = {"conversation_id": self.chat.pk}
            scenario.data = {"client_id": "request-1", "media_mode": "video"}

    def prepare_session(self, scenario: RequestScenario | None = None) -> None:
        """Start a real controller-managed call before testing admission or termination."""
        self.prepare_call()
        result = start_call(self.normal_user, self.chat.pk, "video", "request-1")
        self.session = ConferenceSession.objects.get(pk=result["session_id"])
        if scenario is not None:
            scenario.view_kwargs = {"session_id": self.session.pk}

    def revoke_member(self, scenario: RequestScenario) -> None:
        """Remove current chat eligibility while preserving historical invitation records."""
        self.prepare_session(scenario)
        self.member.left_at = timezone.now()
        self.member.save()

    def ended_session(self, scenario: RequestScenario) -> None:
        """Close a session before a subsequent join or idempotent end request."""
        self.prepare_session(scenario)
        ConferenceController(self.normal_user).end(self.session.pk)

    def connection_event(
        self,
        event_id: str,
        kind: str,
        identity: str,
        *,
        sid: str = "PA_test",
        offset: int = 0,
    ) -> api.WebhookEvent:
        """Build a realistic signed-identity event with deterministic provider times."""
        now = int(timezone.now().timestamp())
        return api.WebhookEvent(
            id=event_id,
            event=kind,
            created_at=now + offset,
            room=api.Room(name=self.session.livekit_room_name, sid="RM_test"),
            participant=api.ParticipantInfo(sid=sid, identity=identity, joined_at=now),
        )
