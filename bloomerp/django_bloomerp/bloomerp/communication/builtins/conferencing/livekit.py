"""LiveKit SDK boundary for trusted conferencing services, without ORM or IM coupling.

Callers must authorize the actor and validate the session before issuing join
credentials or managing a room. This adapter is not a user-facing entrypoint.
"""

import json
from dataclasses import dataclass, field
from datetime import timedelta

from aiohttp import ClientTimeout
from livekit import api

from .configuration import get_conferencing_settings


@dataclass(frozen=True)
class ConferenceJoinCredentials:
    """Browser connection details; never include the server API credentials."""

    url: str
    token: str = field(repr=False)


class LiveKitClient:
    """Use the current instance's explicit configuration for every SDK operation."""

    def __init__(self) -> None:
        """Snapshot validated instance settings without opening network connections."""
        self._settings = get_conferencing_settings()

    def _api(self) -> api.LiveKitAPI:
        """Create an asynchronous SDK client in the caller's running event loop."""
        return api.LiveKitAPI(
            url=self._settings.api_url,
            api_key=self._settings.api_key,
            api_secret=self._settings.api_secret.get_secret_value(),
            timeout=ClientTimeout(total=self._settings.api_timeout_seconds),
            failover=False,
        )

    def issue_join_credentials(
        self,
        room_name: str,
        identity: str,
        display_name: str,
        *,
        allow_video: bool = True,
        allow_screen_share: bool = False,
        presentation: dict[str, str] | None = None,
    ) -> ConferenceJoinCredentials:
        """Sign scoped media grants after the calling service has authorized access."""
        if not room_name.strip() or not identity.strip():
            raise ValueError("A room name and participant identity are required.")
        token = (
            api.AccessToken(
                self._settings.api_key, self._settings.api_secret.get_secret_value()
            )
            .with_identity(identity)
            .with_name(display_name)
            .with_metadata(json.dumps(presentation or {}))
            .with_ttl(timedelta(seconds=self._settings.join_token_ttl_seconds))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    room_create=False,
                    room_list=False,
                    room_admin=False,
                    room_record=False,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=False,
                    can_publish_sources=(
                        ["microphone"]
                        + (["camera"] if allow_video else [])
                        + (
                            ["screen_share", "screen_share_audio"]
                            if allow_screen_share
                            else []
                        )
                    ),
                    can_update_own_metadata=False,
                )
            )
            .to_jwt()
        )
        return ConferenceJoinCredentials(url=self._settings.public_url, token=token)

    async def create_room(
        self, room_name: str, *, max_participants: int, empty_timeout: int = 300
    ) -> api.Room:
        """Provision a temporary media room with explicit capacity and idle timeout."""
        if not room_name.strip() or max_participants < 1 or empty_timeout < 1:
            raise ValueError("A room name, positive capacity and timeout are required.")
        async with self._api() as client:
            return await client.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    max_participants=max_participants,
                    empty_timeout=empty_timeout,
                )
            )

    async def delete_room(self, room_name: str) -> None:
        """Close the media room and disconnect its participants."""
        async with self._api() as client:
            await client.room.delete_room(api.DeleteRoomRequest(room=room_name))

    async def list_participants(self, room_name: str) -> list[api.ParticipantInfo]:
        """Read current connections for attendance reconciliation."""
        async with self._api() as client:
            response = await client.room.list_participants(
                api.ListParticipantsRequest(room=room_name)
            )
            return list(response.participants)

    async def remove_participant(self, room_name: str, identity: str) -> None:
        """Disconnect an explicitly identified participant after service authorization."""
        async with self._api() as client:
            await client.room.remove_participant(
                api.RoomParticipantIdentity(room=room_name, identity=identity)
            )

    def verify_webhook(self, body: str, authorization: str) -> api.WebhookEvent:
        """Verify the signature and raw-body hash before returning a provider event."""
        receiver = api.WebhookReceiver(
            api.TokenVerifier(
                self._settings.api_key,
                self._settings.api_secret.get_secret_value(),
            )
        )
        event = receiver.receive(body, authorization)
        if not event.id:
            raise ValueError(
                "LiveKit webhooks must include an event ID for deduplication."
            )
        return event
