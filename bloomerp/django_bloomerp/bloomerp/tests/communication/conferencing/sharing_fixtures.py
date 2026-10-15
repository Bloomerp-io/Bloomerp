"""Shared graphs for generated meeting admission endpoint cases."""

from django.http import HttpResponse

from bloomerp.models.communication.conferencing import (
    ConferenceAdmission,
)
from bloomerp.tests.base import RequestScenario

from .fixtures import CallFixtures


class SharingFixtures(CallFixtures):
    """Prepare live meetings and verify minimal public responses."""

    def prepare_link(self, scenario: RequestScenario) -> None:
        """Create an IM-origin meeting and supply its unguessable link token."""
        self.prepare_session()
        scenario.view_kwargs = {"token": self.session.share_token}

    def prepare_waiting(self, scenario: RequestScenario) -> None:
        """Queue a named anonymous guest for host-only list and decision endpoints."""
        self.prepare_link(scenario)
        self.admission = ConferenceAdmission.objects.create(
            session=self.session, display_name="Guest <script>"
        )
        scenario.view_kwargs = {"session_id": self.session.pk}

    def prepare_decision(self, scenario: RequestScenario) -> None:
        """Point a host request at exactly one pending admission."""
        self.prepare_waiting(scenario)
        scenario.view_kwargs["admission_id"] = self.admission.pk

    def waiting_created(self, response: HttpResponse) -> bool:
        """Verify asking to join never grants a token or creates a media participant."""
        admission = ConferenceAdmission.objects.get(session=self.session)
        return (
            admission.status == "waiting"
            and admission.participant_id is None
            and "token" not in response.json()
            and self.session.participants.count() == 2
        )

    def account_identity(self, response: HttpResponse) -> bool:
        """Ignore submitted names for authenticated account identities."""
        admission = ConferenceAdmission.objects.get(session=self.session)
        return (
            self.waiting_created(response)
            and admission.user_id == self.admin_user.pk
            and admission.display_name
            == (self.admin_user.get_full_name() or str(self.admin_user))
        )

    def admitted(self, response: HttpResponse) -> bool:
        """Create an admitted participant without changing source chat membership."""
        self.admission.refresh_from_db()
        return (
            self.admission.status == "admitted"
            and self.admission.participant.user_id is None
            and self.chat.participants.count() == 2
        )

    def rejected(self, response: HttpResponse) -> bool:
        """A rejected visitor has no media participant or join credentials."""
        self.admission.refresh_from_db()
        return (
            self.admission.status == "rejected"
            and self.admission.participant_id is None
        )
