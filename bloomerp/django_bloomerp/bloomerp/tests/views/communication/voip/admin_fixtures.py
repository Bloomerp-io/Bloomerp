"""Permission-scoped connection administration fixtures."""

from unittest.mock import patch
from django.http import HttpResponse
from bloomerp.tests.models.communication.voip.fixtures import VoIPFixtures
from bloomerp.tests.base import RequestScenario
from bloomerp.permissions.manager import (
    PolicyManager,
    ensure_bloomerp_model_permissions,
)
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.filters.definition import FilterCondition
from bloomerp.models.communication.voip import VoIPConnection
from bloomerp.communication.builtins.voip.definition import VoIPNumberData


class VoIPAdministrationFixtures(VoIPFixtures):
    """Grant actual row policies and isolate carrier requests from real accounts."""

    def prepare_account(self, scenario: RequestScenario) -> None:
        """Create an account and bounded mocked inventory without authorizing normal staff."""
        self.prepare_voip()
        scenario.view_kwargs = {"pk": self.connection.pk}
        self.adapter = self.enterContext(
            patch("bloomerp.communication.builtins.voip.controller.adapter_for")
        ).return_value
        self.enterContext(
            patch(
                "bloomerp.views.communication.create_voip_number.adapter_for",
                return_value=self.adapter,
            )
        )
        self.adapter.search_numbers.return_value = (
            VoIPNumberData("", "+32470000008", "Available line", True, True),
        )
        self.adapter.list_numbers.return_value = ()
        self.adapter.provision_number.return_value = VoIPNumberData(
            "PN" + "8" * 32, "+32470000008", "New line", True, True
        )

    def grant_connection_access(self, scenario: RequestScenario) -> None:
        """Authorize a non-owner for this connection using the ordinary permission system."""
        ensure_bloomerp_model_permissions()
        policy = PolicyManager.create_policy(
            VoIPConnection,
            field_permissions={"__all__": ["view", "change"]},
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view", "change"],
                    conditions=[
                        FilterCondition(
                            field_path="id",
                            lookup_id="equals",
                            value=str(self.connection.pk),
                        )
                    ],
                )
            ],
        )
        PolicyManager.assign(policy, self.normal_user)

    def prepare_owner_without_permission(self, scenario: RequestScenario) -> None:
        """Prove ownership does not replace an object change grant."""
        self.prepare_account(scenario)
        self.connection.created_by = self.normal_user
        self.connection.save()

    def no_secrets(self, response: HttpResponse) -> bool:
        """Check no decrypted account secret appears in an administration response."""
        return (
            "test-auth-token" not in response.content.decode()
            and "test-api-secret" not in response.content.decode()
        )
