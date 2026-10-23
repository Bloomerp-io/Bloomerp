"""Provider-neutral registration contracts for email transports and authorization."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from .base_adapter import BaseEmailAdapter


class EmailSyncMode(Enum):
    """Synchronization strategies understood by the shared email dispatcher."""

    POLLING = "polling"
    PUSH = "push"

    @property
    def label(self) -> str:
        """Return the human-readable synchronization mode."""
        return self.value.title()


def _default_sync_modes() -> list[EmailSyncMode]:
    """Give each provider its own backwards-compatible list of polling modes."""
    return [EmailSyncMode.POLLING]


@dataclass(frozen=True)
class EmailSyncCapability:
    """Declare a provider's supported scheduling strategies and defaults."""

    default_mode: EmailSyncMode = EmailSyncMode.POLLING
    default_poll_interval_minutes: int = 5
    supported_modes: list[EmailSyncMode] = field(default_factory=_default_sync_modes)


class StartEmailAuthorization(Protocol):
    """Build a consent URL using the framework's state and PKCE verifier."""

    def __call__(
        self,
        adapter: BaseEmailAdapter,
        *,
        redirect_uri: str,
        state: str,
        code_verifier: str,
    ) -> str:
        """Return the remote authorization URL without persisting an account."""
        ...


class CompleteEmailAuthorization(Protocol):
    """Exchange a code and populate the candidate account's verified credentials."""

    def __call__(
        self,
        adapter: BaseEmailAdapter,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> None:
        """Validate consent and identity before filling tokens on the candidate."""
        ...


@dataclass(frozen=True)
class EmailAuthorizationDefinition:
    """Opt into shared authorization, callback, reconnect and disconnect handling."""

    start: StartEmailAuthorization
    complete: CompleteEmailAuthorization
    label: str = "Connect account"
    disconnect: Callable[[BaseEmailAdapter], None] | None = None
    prepare: Callable[[BaseEmailAdapter], None] | None = None


@dataclass(frozen=True)
class EmailProviderDefinition:
    """Register transport behavior and optional capabilities without vendor branching."""

    key: str
    name: str
    description: str
    icon: str
    adapter_class: type[BaseEmailAdapter]
    fields: list[str] = field(default_factory=list)
    required_fields: list[str] = field(default_factory=list)
    initial: dict[str, Any] = field(default_factory=dict)
    setup_instructions: str | None = None
    sync_capabilities: EmailSyncCapability = field(default_factory=EmailSyncCapability)
    authorization: EmailAuthorizationDefinition | None = None
    mailbox_defaults: Callable[[BaseEmailAdapter], dict[str, dict[str, Any]]] | None = (
        None
    )
