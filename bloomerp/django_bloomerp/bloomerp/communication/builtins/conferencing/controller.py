"""Authorized call lifecycle orchestration independent of any IM provider key."""

from collections.abc import Iterable
from uuid import UUID, uuid4

from asgiref.sync import async_to_sync
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from livekit.api import TwirpError

from bloomerp.models.communication.conferencing import (
    ConferenceParticipant,
    ConferenceRoom,
    ConferenceSession,
)
from bloomerp.models.users.user import AbstractBloomerpUser

from .access import authorized_session, require_participant
from .configuration import get_conferencing_settings
from .livekit import LiveKitClient

OPEN_STATES = {"pending", "ringing", "active"}
IDENTITY_SALT = "bloomerp.conferencing.connection"


class ConferenceUnavailable(Exception):
    """The media service outcome is uncertain and can be retried safely."""


def session_payload(session: ConferenceSession) -> dict[str, str]:
    """Return application identifiers and endpoints without transport credentials."""
    return {
        "session_id": str(session.pk),
        "room_id": str(session.room_id),
        "status": session.status,
        "media_mode": session.initial_media_mode,
        "join_url": reverse(
            "components_conferencing_join", kwargs={"session_id": session.pk}
        ),
        "end_url": reverse(
            "components_conferencing_end", kwargs={"session_id": session.pk}
        ),
    }


def publish_session(session_id: UUID) -> None:
    """Publish committed call state to invited users and the optional source hook."""
    from channels.layers import get_channel_layer

    from bloomerp.utils.callables import resolve_hook

    session = ConferenceSession.objects.select_related("room__conversation").get(
        pk=session_id
    )
    layer = get_channel_layer()
    if layer:
        for participant in session.participants.filter(
            user__is_active=True
        ).select_related("user"):
            try:
                require_participant(participant.user, session)
            except PermissionDenied:
                continue
            async_to_sync(layer.group_send)(
                f"user_{participant.user_id}",
                {
                    "type": "notify",
                    "payload": {
                        "action": "conferencing.session.changed",
                        **session_payload(session),
                    },
                },
            )
    if session.room.conversation_id:
        from bloomerp.communication.builtins.instant_messaging.calling import (
            calling_definition,
        )

        definition = calling_definition(session.room.conversation)
        if definition and definition.session_changed_handler:
            resolve_hook(definition.session_changed_handler)(session)


def notify_after_commit(session: ConferenceSession) -> None:
    """Schedule notifications only after the database state is durable."""
    session_id = session.pk

    def publish_committed_session() -> None:
        """Publish durable state using a named callback Django can safely log."""
        publish_session(session_id)

    transaction.on_commit(publish_committed_session, robust=True)


def delete_media_room(room_name: str) -> None:
    """Close a media room idempotently, treating missing rooms as already closed."""
    try:
        async_to_sync(LiveKitClient().delete_room)(room_name)
    except TwirpError as error:
        if error.code != "not_found":
            raise ConferenceUnavailable from error
    except Exception as error:
        raise ConferenceUnavailable from error


class ConferenceController:
    """Manage calls for one actor, with provider hooks owning source eligibility."""

    def __init__(self, user: AbstractBloomerpUser) -> None:
        """Bind mutations to the authenticated actor rather than request user IDs."""
        self.user = user

    def start(
        self,
        room: ConferenceRoom,
        users: Iterable[AbstractBloomerpUser],
        media_mode: str,
        client_id: str,
    ) -> ConferenceSession:
        """Reserve a call for a trusted source's authorized invitees, then provision it."""
        get_conferencing_settings()
        if not self.user.is_authenticated or not self.user.is_active:
            raise PermissionDenied
        if (
            media_mode not in {"audio", "video"}
            or not client_id
            or len(client_id) > 255
        ):
            raise ValidationError(
                _("A valid call mode and request identifier are required.")
            )
        invitees = {user.pk: user for user in users if user.is_active}
        if self.user.pk not in invitees:
            raise PermissionDenied
        # A source provider must supply its authorized users. Standalone room
        # initiation is restricted to its creator until calendar grants exist.
        if room.conversation_id:
            from bloomerp.communication.builtins.instant_messaging.calling import (
                call_capabilities,
                call_participants,
            )

            capabilities = call_capabilities(self.user, room.conversation)
            eligible = {
                user.pk for user in call_participants(self.user, room.conversation)
            }
            if not getattr(capabilities, media_mode) or not set(invitees).issubset(
                eligible
            ):
                raise PermissionDenied
            if len(invitees) > 2 and not capabilities.groups:
                raise PermissionDenied
        elif room.created_by_id != self.user.pk:
            raise PermissionDenied
        with transaction.atomic():
            room = ConferenceRoom.objects.select_for_update().get(pk=room.pk)
            if room.archived:
                raise ValidationError(_("This room is archived."))
            session = room.sessions.filter(client_id=client_id).first()
            if session:
                participant = require_participant(self.user, session)
                if (
                    participant.role != "host"
                    or session.initial_media_mode != media_mode
                ):
                    raise PermissionDenied
            else:
                if room.sessions.filter(status__in=OPEN_STATES).exists():
                    raise ValidationError(
                        _("A call is already open. Use Join call in the conversation."),
                        code="call_already_open",
                    )
                session = ConferenceSession.objects.create(
                    room=room,
                    initial_media_mode=media_mode,
                    client_id=client_id,
                    created_by=self.user,
                )
                for user in invitees.values():
                    ConferenceParticipant.objects.create(
                        session=session,
                        user=user,
                        display_name_snapshot=str(user),
                        role="host" if user.pk == self.user.pk else "participant",
                        invited_at=timezone.now(),
                    )
        return self._provision(session.pk)

    def _provision(self, session_id: UUID) -> ConferenceSession:
        """Retry uncertain provisioning with the same room name and serialize closing."""
        with transaction.atomic():
            session = ConferenceSession.objects.select_for_update().get(pk=session_id)
            if session.status != "pending":
                return session
            require_participant(self.user, session)
            try:
                remote = async_to_sync(LiveKitClient().create_room)(
                    session.livekit_room_name,
                    max_participants=max(
                        get_conferencing_settings().max_participants,
                        session.participants.count() * 2,
                    ),
                )
            except Exception as error:
                # Keep the committed reservation: a timeout may have created it.
                raise ConferenceUnavailable from error
            session.livekit_room_sid = remote.sid
            session.status = "ringing"
            session.save()
            notify_after_commit(session)
            return session

    def join(self, session_id: UUID) -> dict[str, str]:
        """Issue a connection identity only after checking current invitation and source access."""
        authorized_session(self.user, session_id)
        with transaction.atomic():
            session = (
                ConferenceSession.objects.select_for_update()
                .select_related("room__conversation")
                .get(pk=session_id)
            )
            participant = require_participant(self.user, session)
            if session.status not in {"ringing", "active"} or session.room.archived:
                raise ValidationError(_("This call is not available to join."))
            allow_video = True
            allow_screen_share = True
            if session.room.conversation_id:
                from bloomerp.communication.builtins.instant_messaging.calling import (
                    call_capabilities,
                )

                capabilities = call_capabilities(self.user, session.room.conversation)
                allow_video = capabilities.video
                allow_screen_share = capabilities.screen_share
                if not getattr(capabilities, session.initial_media_mode):
                    raise PermissionDenied
            identity = signing.Signer(salt=IDENTITY_SALT).sign_object(
                {"participant": str(participant.pk), "nonce": uuid4().hex},
                compress=True,
            )
            presentation = {
                "displayName": participant.display_name_snapshot,
                "initials": "".join(
                    part[0] for part in participant.display_name_snapshot.split()[:2]
                ),
                "avatar": self.user.avatar.url if self.user.avatar else "",
            }
            if session.room.conversation_id:
                from bloomerp.communication.builtins.instant_messaging.presentation import (
                    participant_identity,
                )

                member = (
                    session.room.conversation.participants.select_related(
                        "user", "identity", "conversation"
                    )
                    .filter(user=self.user, left_at__isnull=True)
                    .first()
                )
                if member is not None:
                    presentation = participant_identity(member, self.user.pk)
            credentials = LiveKitClient().issue_join_credentials(
                session.livekit_room_name,
                identity,
                presentation["displayName"],
                allow_video=allow_video,
                allow_screen_share=allow_screen_share,
                presentation=presentation,
            )
            participant.invitation_status = "accepted"
            participant.responded_at = participant.responded_at or timezone.now()
            participant.save()
            from .sharing import sharing_controls

            return {
                **session_payload(session),
                **sharing_controls(session, participant),
                "url": credentials.url,
                "token": credentials.token,
                "identity": identity,
                "driver": self.browser_driver(session),
                "can_video": "true" if allow_video else "false",
                "can_screen_share": "true" if allow_screen_share else "false",
                "can_end": "true" if participant.role == "host" else "false",
            }

    def browser_driver(self, session: ConferenceSession) -> str:
        """Resolve the browser transport declared by the source provider."""
        if session.room.conversation_id:
            from bloomerp.communication.builtins.instant_messaging.calling import (
                calling_definition,
            )

            definition = calling_definition(session.room.conversation)
            if not definition or not definition.browser_driver:
                raise ValidationError(
                    _("Browser calling is unavailable for this provider.")
                )
            return definition.browser_driver
        return "livekit"

    def end(self, session_id: UUID) -> ConferenceSession:
        """End for everyone as the host; repeat requests retry media cleanup safely."""
        authorized_session(self.user, session_id)
        with transaction.atomic():
            session = ConferenceSession.objects.select_for_update().get(pk=session_id)
            if require_participant(self.user, session).role != "host":
                raise PermissionDenied
            if session.status in OPEN_STATES:
                session.status = "ended" if session.started_at else "cancelled"
                session.ended_at = (
                    max(timezone.now(), session.started_at)
                    if session.started_at
                    else timezone.now()
                )
                session.end_reason = "host_ended"
                session.save()
                close_attendance(session)
                notify_after_commit(session)
        # Persist closure first so no new join tokens can be issued if deletion fails.
        delete_media_room(session.livekit_room_name)
        return session


def close_attendance(session: ConferenceSession) -> None:
    """Close observed connections and unanswered invitations after a call finishes."""
    for participant in session.participants.all():
        for attendance in participant.attendances.filter(left_at__isnull=True):
            attendance.left_at = max(session.ended_at, attendance.joined_at)
            attendance.leave_reason = session.end_reason
            attendance.save()
        if participant.invitation_status == "invited":
            participant.invitation_status = "missed"
            participant.save()
