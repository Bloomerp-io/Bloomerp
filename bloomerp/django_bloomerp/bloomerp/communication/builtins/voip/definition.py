"""Typed carrier contracts, separate from conversation and database persistence."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, ClassVar
from django.http import HttpRequest
from pydantic import BaseModel, ConfigDict, Field
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class VoIPCapabilities:
    """Describe effective transport operations for one configured account."""

    sms: bool = False
    voice: bool = False
    browser_calling: bool = False
    history_sync: bool = False


@dataclass(frozen=True)
class VoIPNumberData:
    """Normalize a provider-owned number without local assignments or labels."""

    external_id: str
    number: str
    name: str
    sms: bool
    voice: bool


@dataclass(frozen=True)
class VoIPCallData:
    """Normalize one provider leg for idempotent history reconciliation."""

    external_id: str
    parent_id: str
    from_address: str
    to_address: str
    direction: str
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    duration: int


@dataclass(frozen=True)
class VoIPContext:
    """Supply server-only credentials and nonsecret connection configuration."""

    connection_id: str
    account_id: str
    settings: Mapping[str, Any] = field(repr=False)
    credentials: Mapping[str, str] = field(repr=False)


class VoIPConfiguration(BaseModel):
    """Define common typed setup fields for carrier connection wizards."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255, title=_("Connection name"))

    def external_account_id(self) -> str:
        """Return the account identifier used to bind verified webhooks."""
        raise NotImplementedError


class VoIPNumberOptions(BaseModel):
    """Validate provider-owned operation inputs without accepting undeclared keys."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    field_choices: ClassVar[Mapping[str, tuple[tuple[str, str], ...]]] = {}


class BaseVoIPAdapter(ABC):
    """Normalize carrier operations without owning database or inbox writes."""

    provider_key: str

    def __init__(self, context: VoIPContext) -> None:
        """Bind a carrier adapter to one configured account."""
        self.context = context

    @abstractmethod
    def validate_connection(self) -> VoIPCapabilities:
        """Verify account access and return effective capabilities."""
        raise NotImplementedError

    @abstractmethod
    def list_numbers(self) -> tuple[VoIPNumberData, ...]:
        """Fetch the complete account inventory before changing local state."""
        raise NotImplementedError

    def sync_calls(self, since: datetime | None) -> tuple[VoIPCallData, ...]:
        """Fetch history when supported by the carrier."""
        raise NotImplementedError

    def send_sms(self, sender: str, recipient: str, body: str, callback: str) -> str:
        """Send an SMS once and return its provider identifier."""
        raise NotImplementedError

    def search_numbers(self, options: Mapping[str, Any]) -> tuple[VoIPNumberData, ...]:
        """Find available carrier numbers without reserving or purchasing them."""
        raise NotImplementedError

    def provision_number(
        self,
        number: str,
        name: str,
        options: Mapping[str, Any],
        callbacks: Mapping[str, str],
    ) -> VoIPNumberData:
        """Purchase one exact number and configure its application callbacks."""
        raise NotImplementedError

    def callback_url(self, kind: str, **kwargs: Any) -> str:
        """Resolve a provider-specific callback address from trusted configuration."""
        raise NotImplementedError

    def verify_request(self, request: HttpRequest, kind: str, **kwargs: Any) -> bool:
        """Reject incoming requests unless the carrier implementation authenticates them."""
        return False

    def browser_token(self, identity: str) -> str:
        """Issue short-lived credentials for one authorized browser identity."""
        raise NotImplementedError


@dataclass(frozen=True)
class VoIPProviderDefinition:
    """Declare carrier setup and transport implementation in the registry."""

    key: str
    display_name: str
    icon: str
    description: str
    config_schema: type[VoIPConfiguration]
    adapter_class: type[BaseVoIPAdapter]
    number_search_schema: type[VoIPNumberOptions] | None = None
    number_purchase_schema: type[VoIPNumberOptions] | None = None
    purchase_notice: str = ""
    pricing_url: str = ""
    account_id_field: str = ""
    immutable_config_fields: tuple[str, ...] = ()
    callback_labels: Mapping[str, str] = field(default_factory=dict)
    callback_help: str = ""
    configuration_help: str = ""
    webhook_handlers: Mapping[str, str] = field(default_factory=dict)
    browser_driver: str = ""
    operation_errors: tuple[type[Exception], ...] = (ValueError,)
    max_sms_length: int = 1600

    def create_adapter(self, context: VoIPContext) -> BaseVoIPAdapter:
        """Construct a server-side adapter from freshly resolved secrets."""
        return self.adapter_class(context)
