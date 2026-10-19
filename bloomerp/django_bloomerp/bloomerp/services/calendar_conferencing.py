"""Reserve future calendar meetings without provisioning live media rooms."""

from collections.abc import Iterable
from urllib.parse import urljoin

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from bloomerp.communication.builtins.conferencing.configuration import (
    get_conferencing_settings,
)
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.communication.conferencing import (
    ConferenceParticipant,
    ConferenceRoom,
    ConferenceSession,
)
from bloomerp.models.users.user import AbstractBloomerpUser


@transaction.atomic
def reserve_calendar_conference(
    event: CalendarEvent,
    host: AbstractBloomerpUser,
    attendees: Iterable[AbstractBloomerpUser],
    base_url: str,
) -> str:
    """Persist a source-bound pending meeting and return its stable, host-admitted join link."""
    get_conferencing_settings()
    room = ConferenceRoom.objects.create(title=event.title, created_by=host)
    session = ConferenceSession.objects.create(
        room=room, initial_media_mode="video", created_by=host
    )
    users = {person.pk: person for person in [host, *attendees]}
    for person in users.values():
        ConferenceParticipant.objects.create(
            session=session,
            user=person,
            display_name_snapshot=str(person),
            role="host" if person.pk == host.pk else "participant",
            created_by=host,
            invited_at=timezone.now(),
        )
    event.conference_session = session
    event.save(update_fields=["conference_session"])
    return urljoin(
        base_url,
        reverse("conference_sessions_meeting", kwargs={"token": session.share_token}),
    )
