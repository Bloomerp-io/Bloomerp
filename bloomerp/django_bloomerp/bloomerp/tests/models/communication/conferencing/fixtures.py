"""Small shared graphs for generated conferencing model scenarios."""

from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone

from bloomerp.models.communication.conferencing import (
    ConferenceParticipant,
    ConferenceRoom,
    ConferenceSession,
)


class ConferenceFixtures:
    """Create independent rooms and a user without requiring IM records."""

    def prepare(self) -> None:
        """Create the graph needed to exercise conference lifecycle invariants."""
        self.room = ConferenceRoom.objects.create(title="Planning")
        self.other_room = ConferenceRoom.objects.create(title="Support")
        self.user = get_user_model().objects.create_user(username="conference-user")
        self.session = ConferenceSession.objects.create(room=self.room)
        self.participant = ConferenceParticipant.objects.create(
            session=self.session,
            user=self.user,
            display_name_snapshot="Conference user",
        )
        self.now = timezone.now()

    def session_args(self, **overrides: Any) -> dict[str, Any]:
        """Build arguments for another room's session."""
        return {"room": self.other_room, **overrides}

    def participant_args(self, **overrides: Any) -> dict[str, Any]:
        """Build an unlinked historical participant in the existing session."""
        return {
            "session": self.session,
            "display_name_snapshot": "Historical participant",
            **overrides,
        }

    def attendance_args(self, **overrides: Any) -> dict[str, Any]:
        """Build a connected attendance record."""
        return {"participant": self.participant, "joined_at": self.now, **overrides}
