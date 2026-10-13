"""Authorized component fixtures with transport calls isolated from real accounts."""

from unittest.mock import patch
from django.http import HttpResponse
from bloomerp.tests.base import RequestScenario
from bloomerp.tests.models.communication.voip.fixtures import VoIPFixtures
from bloomerp.communication.builtins.voip.definition import (
    VoIPCapabilities,
    VoIPNumberData,
)


class ComponentFixtures(VoIPFixtures):
    """Prepare active lines and mocked carrier boundaries for HTTP scenarios."""

    def prepare_request(self, scenario: RequestScenario) -> None:
        """Resolve the generated route's arguments against a real authorized graph."""
        self.prepare_voip()
        scenario.view_kwargs = {}
        if self.view_name in {"components_voip_token", "components_voip_sync"}:
            scenario.view_kwargs = {"connection_id": self.connection.pk}
        elif self.view_name == "components_voip_start_call":
            scenario.view_kwargs = {"conversation_id": self.chat.pk}
            scenario.data = {"client_id": "browser-request"}
        elif self.view_name == "components_voip_assign":
            scenario.view_kwargs = {"number_id": self.number.pk}
            scenario.data = {"users": [str(self.normal_user.pk)]}
        self.adapter = self.enterContext(
            patch("bloomerp.communication.builtins.voip.controller.adapter_for")
        ).return_value
        self.adapter.validate_connection.return_value = VoIPCapabilities(
            sms=True, voice=True, browser_calling=True, history_sync=True
        )
        self.adapter.list_numbers.return_value = (
            VoIPNumberData(
                self.number.provider_number_id,
                self.number.number,
                "Provider label",
                True,
                True,
            ),
        )
        self.adapter.sync_calls.return_value = ()
        self.enterContext(
            patch("bloomerp.components.communication.voip.browser_token.adapter_for")
        ).return_value.browser_token.return_value = "short-lived-token"

    def revoke_line(self, scenario: RequestScenario) -> None:
        """Keep chat membership while revoking the right to use its telephone line."""
        self.prepare_request(scenario)
        self.number.assigned_users.clear()

    def validate_no_secrets(self, response: HttpResponse) -> bool:
        """Ensure browser and synchronization payloads contain no long-lived credentials."""
        return (
            "test-auth-token" not in response.content.decode()
            and "test-api-secret" not in response.content.decode()
        )
