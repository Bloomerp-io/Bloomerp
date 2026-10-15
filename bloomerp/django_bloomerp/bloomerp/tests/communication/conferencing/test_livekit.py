"""SDK contract tests using real token signatures and mocked network transport."""

import base64
import hashlib
import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
from django.test import SimpleTestCase, override_settings
from livekit import api

from bloomerp.communication.builtins.conferencing.livekit import LiveKitClient

from .test_configuration import conferencing_config


@override_settings(BLOOMERP_CONFIG=conferencing_config())
class TestLiveKitClient(SimpleTestCase):
    """Keep server secrets private and network operations tied to one instance."""

    def test_join_token_is_scoped_and_short_lived(self) -> None:
        """Use case: Issue join credentials. Expected result: scoped media grants only."""
        # 1. Sign and independently verify a browser token.
        credentials = LiveKitClient().issue_join_credentials(
            "room-one", "device-one", "Alice"
        )
        claims = jwt.decode(
            credentials.token,
            "instance-secret-at-least-32-characters",
            algorithms=["HS256"],
            issuer="instance-key",
        )
        # 2. Assert room, identity, expiration and lack of administration grants.
        self.assertEqual(credentials.url, "wss://calls.example.test")
        self.assertEqual(claims["sub"], "device-one")
        self.assertEqual(claims["video"]["room"], "room-one")
        self.assertTrue(claims["video"]["roomJoin"])
        for grant in [
            "roomAdmin",
            "roomCreate",
            "roomList",
            "roomRecord",
            "canPublishData",
        ]:
            self.assertFalse(claims["video"][grant])
        self.assertEqual(claims["exp"] - claims["nbf"], 300)
        self.assertNotIn(credentials.token, repr(credentials))
        with self.assertRaises(jwt.InvalidSignatureError):
            jwt.decode(
                credentials.token,
                "another-instance-secret-32-characters",
                algorithms=["HS256"],
            )

    def test_webhook_signature_body_hash_and_event_id(self) -> None:
        """Use case: Receive callbacks. Expected result: accept only intact signed events."""
        # 1. Sign the exact raw event body using the real SDK.
        client = LiveKitClient()
        body = json.dumps(
            {"event": "room_started", "id": "EV_one", "room": {"name": "room-one"}}
        )
        digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        authorization = (
            api.AccessToken("instance-key", "instance-secret-at-least-32-characters")
            .with_sha256(digest)
            .with_ttl(timedelta(minutes=1))
            .to_jwt()
        )
        self.assertEqual(client.verify_webhook(body, authorization).id, "EV_one")
        # 2. Reject a modified body and a token signed by a different instance.
        with self.assertRaisesRegex(Exception, "hash mismatch"):
            client.verify_webhook(body + " ", authorization)
        foreign = (
            api.AccessToken("other-key", "another-instance-secret-32-characters")
            .with_sha256(digest)
            .to_jwt()
        )
        with self.assertRaises(jwt.InvalidTokenError):
            client.verify_webhook(body, foreign)
        empty = json.dumps({"event": "room_started"})
        empty_hash = base64.b64encode(hashlib.sha256(empty.encode()).digest()).decode()
        empty_token = (
            api.AccessToken("instance-key", "instance-secret-at-least-32-characters")
            .with_sha256(empty_hash)
            .to_jwt()
        )
        with self.assertRaises(ValueError):
            client.verify_webhook(empty, empty_token)

    async def test_room_management_uses_configured_api_and_closes_client(self) -> None:
        """Use case: Manage media rooms. Expected result: scoped SDK requests and closed clients."""
        # 1. Substitute only network transport while retaining SDK request types.
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.room.create_room = AsyncMock(
            return_value=api.Room(name="room-one", sid="RM_one")
        )
        client.room.list_participants = AsyncMock(
            return_value=api.ListParticipantsResponse(
                participants=[api.ParticipantInfo(identity="device-one")]
            )
        )
        client.room.remove_participant = AsyncMock()
        client.room.delete_room = AsyncMock()
        with patch(
            "bloomerp.communication.builtins.conferencing.livekit.api.LiveKitAPI",
            return_value=client,
        ) as factory:
            adapter = LiveKitClient()
            room = await adapter.create_room("room-one", max_participants=6)
            participants = await adapter.list_participants("room-one")
            await adapter.remove_participant("room-one", "device-one")
            await adapter.delete_room("room-one")
        # 2. Verify deployment address, room constraints and resource cleanup.
        self.assertEqual(room.sid, "RM_one")
        self.assertEqual(participants[0].identity, "device-one")
        self.assertEqual(factory.call_args.kwargs["url"], "http://livekit:7880")
        self.assertFalse(factory.call_args.kwargs["failover"])
        self.assertEqual(client.room.create_room.call_args.args[0].max_participants, 6)
        self.assertEqual(
            client.room.remove_participant.call_args.args[0].identity, "device-one"
        )
        self.assertEqual(client.room.delete_room.call_args.args[0].room, "room-one")
        self.assertEqual(client.__aexit__.await_count, 4)

    async def test_sdk_failure_closes_client(self) -> None:
        """Use case: Unreachable LiveKit. Expected result: propagate failure and release resources."""
        # 1. Simulate an unavailable media server.
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.room.create_room = AsyncMock(side_effect=TimeoutError)
        with (
            patch(
                "bloomerp.communication.builtins.conferencing.livekit.api.LiveKitAPI",
                return_value=client,
            ),
            self.assertRaises(TimeoutError),
        ):
            await LiveKitClient().create_room("room-one", max_participants=6)
        # 2. Verify cleanup even when the network operation fails.
        client.__aexit__.assert_awaited_once()

    def test_audio_only_grants_exclude_video_sources(self) -> None:
        """Use case: Audio-only provider. Expected result: token cannot publish camera or screen tracks."""
        # 1. Request scoped admission without video publication support.
        credentials = LiveKitClient().issue_join_credentials(
            "room-audio", "device", "Alice", allow_video=False
        )
        claims = jwt.decode(
            credentials.token,
            "instance-secret-at-least-32-characters",
            algorithms=["HS256"],
        )
        # 2. Enforce provider restrictions at the media server, not just in the UI.
        self.assertEqual(claims["video"]["canPublishSources"], ["microphone"])
