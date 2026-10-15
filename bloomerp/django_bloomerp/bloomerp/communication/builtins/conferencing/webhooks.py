"""Verified, idempotent and order-tolerant LiveKit event reconciliation."""

from datetime import UTC, datetime

from asgiref.sync import async_to_sync
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from livekit import api

from bloomerp.models.communication.conferencing import (
    ConferenceAttendance,
    ConferenceParticipant,
    ConferenceSession,
    ConferenceWebhookReceipt,
)

from .access import require_participant
from .controller import (
    IDENTITY_SALT,
    OPEN_STATES,
    close_attendance,
    delete_media_room,
    notify_after_commit,
)
from .livekit import LiveKitClient


def event_time(seconds: int) -> datetime:
    """Convert a positive provider timestamp into an aware UTC datetime."""
    if seconds <= 0:
        raise ValidationError("LiveKit event timestamps must be positive.")
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (ValueError, OverflowError, OSError) as error:
        raise ValidationError("Invalid LiveKit timestamp.") from error


def identity_participant(
    identity: str, session: ConferenceSession
) -> ConferenceParticipant | None:
    """Accept only server-issued connection identities bound to this exact session."""
    try:
        payload = signing.Signer(salt=IDENTITY_SALT).unsign_object(identity)
        return (
            session.participants.select_related("user")
            .filter(pk=payload["participant"])
            .first()
        )
    except (signing.BadSignature, ValueError, KeyError, TypeError, ValidationError):
        return None


@transaction.atomic
def reconcile_event(event: api.WebhookEvent) -> None:
    """Apply a verified event once; roll back its receipt if processing fails."""
    when = event_time(event.created_at)
    session = (
        ConferenceSession.objects.select_for_update()
        # Keep nullable conversation reads outside the locking query.
        .select_related("room")
        .filter(livekit_room_name=event.room.name)
        .first()
    )
    if session is None:
        return
    receipt, created = ConferenceWebhookReceipt.objects.get_or_create(
        event_id=event.id, defaults={"event_type": event.event, "occurred_at": when}
    )
    if not created and receipt.status in {"processed", "ignored"}:
        return
    handled = False
    if (
        event.room.sid
        and session.livekit_room_sid
        and event.room.sid != session.livekit_room_sid
    ):
        # A stale token can recreate an already closed room with a new SID.
        if session.status not in OPEN_STATES and event.event in {
            "room_started",
            "participant_joined",
        }:
            delete_media_room(session.livekit_room_name)
    elif event.event in {
        "room_started",
        "participant_joined",
        "participant_left",
        "room_finished",
    }:
        if event.room.sid and not session.livekit_room_sid:
            session.livekit_room_sid = event.room.sid
        if event.event == "room_finished":
            if session.status in OPEN_STATES:
                session.status = "ended" if session.started_at else "cancelled"
                session.ended_at = (
                    max(when, session.started_at) if session.started_at else when
                )
                session.end_reason = "room_finished"
                session.save()
                close_attendance(session)
            handled = True
        elif session.status not in OPEN_STATES and event.event in {
            "room_started",
            "participant_joined",
        }:
            delete_media_room(session.livekit_room_name)
            handled = True
        elif event.event == "room_started":
            session.save()
            handled = True
        else:
            handled = reconcile_attendance(session, event, when)
        notify_after_commit(session)
    receipt.status = "processed" if handled else "ignored"
    receipt.processed_at = timezone.now()
    receipt.save()


def reconcile_attendance(
    session: ConferenceSession, event: api.WebhookEvent, when: datetime
) -> bool:
    """Retain observed intervals by provider SID without inventing attendance on token issue."""
    remote = event.participant
    participant = identity_participant(remote.identity, session)
    if participant is None or not remote.sid:
        if event.event == "participant_joined" and remote.identity:
            async_to_sync(LiveKitClient().remove_participant)(
                session.livekit_room_name, remote.identity
            )
        return False
    if event.event == "participant_joined":
        try:
            from .sharing import admitted_participant

            if session.room.archived:
                raise PermissionDenied
            if not admitted_participant(participant):
                if participant.user is None or session.room.archived:
                    raise PermissionDenied
                require_participant(participant.user, session)
                if session.room.conversation_id:
                    from bloomerp.communication.builtins.instant_messaging.calling import (
                        call_capabilities,
                    )

                    if not getattr(
                        call_capabilities(participant.user, session.room.conversation),
                        session.initial_media_mode,
                    ):
                        raise PermissionDenied
        except PermissionDenied:
            async_to_sync(LiveKitClient().remove_participant)(
                session.livekit_room_name, remote.identity
            )
            return False
    joined = event_time(remote.joined_at) if remote.joined_at else when
    attendance = ConferenceAttendance.objects.filter(
        livekit_participant_sid=remote.sid
    ).first()
    if attendance and (
        attendance.participant_id != participant.pk
        or attendance.livekit_identity != remote.identity
    ):
        return False
    if attendance is None:
        attendance = ConferenceAttendance(
            participant=participant,
            livekit_identity=remote.identity,
            livekit_participant_sid=remote.sid,
            joined_at=joined,
        )
    if event.event == "participant_left":
        attendance.left_at = attendance.left_at or max(when, attendance.joined_at)
        attendance.leave_reason = "participant_left"
    if session.ended_at:
        attendance.left_at = attendance.left_at or max(
            session.ended_at, attendance.joined_at
        )
    attendance.save()
    if session.status in OPEN_STATES:
        session.started_at = (
            min(session.started_at, joined) if session.started_at else joined
        )
        session.status = "active"
        session.save()
    return True
