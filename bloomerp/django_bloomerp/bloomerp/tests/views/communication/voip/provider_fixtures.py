"""A deliberately non-Twilio carrier for shared administration contract tests."""

from typing import Any
from unittest.mock import patch
from pydantic import Field, SecretStr
from bloomerp.communication.builtins.voip.definition import (
    BaseVoIPAdapter,
    VoIPCapabilities,
    VoIPConfiguration,
    VoIPNumberData,
    VoIPNumberOptions,
    VoIPProviderDefinition,
)
from bloomerp.communication.builtins.voip.registry import VOIP_PROVIDER_REGISTRY
from bloomerp.models.communication.voip import VoIPConnection
from bloomerp.tests.base import RequestScenario
from .admin_fixtures import VoIPAdministrationFixtures


class ExampleConfiguration(VoIPConfiguration):
    """Identify an account without Twilio SIDs or callback settings."""

    account_ref: str = Field(title="Carrier account")
    password: SecretStr = Field(title="Password")

    def external_account_id(self) -> str:
        """Return the alternate carrier's stable account reference."""
        return self.account_ref


class ExampleSearch(VoIPNumberOptions):
    """Search by territory rather than Twilio's country and number type."""

    territory: str = Field(min_length=3, title="Service territory")


class ExamplePurchase(VoIPNumberOptions):
    """Require a numeric plan reference instead of Twilio regulatory SIDs."""

    plan: int = Field(ge=1, title="Service plan")


class ExampleAdapter(BaseVoIPAdapter):
    """Provide only the neutral transport contract needed by the test provider."""

    provider_key = "example"

    def validate_connection(self) -> VoIPCapabilities:
        """Advertise inventory-only functionality for the test carrier."""
        return VoIPCapabilities()

    def list_numbers(self) -> tuple[VoIPNumberData, ...]:
        """Return no owned numbers until the mocked provisioning operation runs."""
        return ()

    def callback_url(self, kind: str, **kwargs: Any) -> str:
        """Resolve a provider URL without shared public_url settings or Twilio routes."""
        return f"https://carrier.example.test/{kind}"


EXAMPLE_PROVIDER = VoIPProviderDefinition(
    key="example",
    display_name="Example carrier",
    icon="fa-phone",
    description="Test carrier",
    config_schema=ExampleConfiguration,
    adapter_class=ExampleAdapter,
    number_search_schema=ExampleSearch,
    number_purchase_schema=ExamplePurchase,
    account_id_field="account_ref",
    purchase_notice="Example carrier purchase terms",
    callback_labels={"events": "Carrier events"},
    callback_help="Example carrier setup",
    browser_driver="example-driver",
    operation_errors=(RuntimeError, ValueError),
)


class AlternateProviderFixtures(VoIPAdministrationFixtures):
    """Exercise actual shared forms and controllers with unrelated carrier controls."""

    def prepare_alternate_provider(self, scenario: RequestScenario) -> None:
        """Register an isolated provider and replace the account fixture's carrier metadata."""
        self.prepare_account(scenario)
        self.enterContext(
            patch.dict(VOIP_PROVIDER_REGISTRY._registry, {"example": EXAMPLE_PROVIDER})
        )
        self.connection = VoIPConnection(
            name="Alternate carrier",
            provider="example",
            external_account_id="account-42",
            status="active",
            settings={"account_ref": "account-42"},
            created_by=self.admin_user,
        )
        self.connection.set_credentials({"password": "example-secret"})
        self.connection.save()
        scenario.view_kwargs = {"pk": self.connection.pk}
