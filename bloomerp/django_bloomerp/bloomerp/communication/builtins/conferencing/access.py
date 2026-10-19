"""Participant-scoped conference access, including current source authorization."""

from uuid import UUID

from bloomerp.models.communication.conferencing import (
    ConferenceParticipant,
    ConferenceSession,
)
from bloomerp.models.users.user import AbstractBloomerpUser
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied


def require_participant(
    user: AbstractBloomerpUser | AnonymousUser, session: ConferenceSession
) -> ConferenceParticipant:
    """Require an active invited account; even superusers must be participants."""
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied
    participant = session.participants.filter(user=user).first()
    if participant is None:
        raise PermissionDenied
    calendar_event = getattr(session, "calendar_event", None)
    if calendar_event is not None and (
        calendar_event.cancelled
        or (
            participant.role != "host"
            and not calendar_event.participants.filter(
                user=user, invitation_cancelled=False
            ).exists()
        )
    ):
        raise PermissionDenied
    if session.room.conversation_id:
        from bloomerp.communication.builtins.instant_messaging.calling import (
            call_participants,
        )

        eligible = call_participants(user, session.room.conversation)
        if user.pk not in {person.pk for person in eligible}:
            raise PermissionDenied
    return participant


def authorized_session(
    user: AbstractBloomerpUser | AnonymousUser, session_id: UUID
) -> ConferenceSession:
    """Resolve a session without exposing whether an inaccessible ID exists."""
    session = (
        ConferenceSession.objects.select_related("room__conversation")
        .filter(pk=session_id)
        .first()
    )
    if session is None:
        raise PermissionDenied
    require_participant(user, session)
    return session
