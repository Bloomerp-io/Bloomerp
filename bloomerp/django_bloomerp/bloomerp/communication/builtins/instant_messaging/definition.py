"""Provider-neutral contracts for IM presentation, discovery and transport.

Adapters never create conversations/messages. Native directory lookup applies
user visibility; the controller rechecks authorization before persistence.
The messaging controller persists once, commits, and then dispatches transport.
Provider IDs are opaque strings scoped by connection (and endpoint as needed).
These DTOs do not depend on Django IM models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from collections.abc import Callable, Iterable
from typing import Any, Literal, Mapping, Protocol, Required, TYPE_CHECKING, TypedDict
from uuid import UUID

from django.http import HttpRequest, HttpResponse

if TYPE_CHECKING:
    from bloomerp.models.base_bloomerp_model import BloomerpModel
    from bloomerp.models.users.user import AbstractBloomerpUser
    from bloomerp.models.communication.instant_messaging import (
        IMConversation, IMIdentity, IMMessage,
    )

from pydantic import BaseModel, ConfigDict, Field

from bloomerp.communication.definition import (
    InboxFolderTypeDefinition,
    InboxItemTypeDefinition,
)
from bloomerp.communication.inbox_sources import InboxEventSource

from .inbox_source import render_inbox_conversation


class IMUnsupportedOperation(NotImplementedError):
    """An operation is outside this connection's supported capabilities."""


class IMAdapterNotReady(NotImplementedError):
    """An adapter is a draft and has no operational provider transport yet."""


@dataclass(frozen=True)
class IMCapabilities:
    """Describe effective connection features; unavailable features default off.

    Directory mode distinguishes a browsable remote directory, contact updates
    received through synchronization, a service-scoped staff directory, and no
    directory. Provider support does not replace per-user authorization.
    """

    groups: bool = False
    create_groups: bool = False
    quoted_replies: bool = False
    threads: bool = False
    attachments: bool = False
    read_receipts: bool = False
    typing: bool = False
    reactions: bool = False
    edits: bool = False
    history_sync: bool = False
    outbound_templates: bool = False
    directory: Literal["none", "staff", "remote", "sync"] = "none"
    manual_address: bool = False


@dataclass(frozen=True)
class IMConnectionContext:
    """Provide server-only account context, separate from provider-wide app secrets.

    Credentials are supplied decrypted by the server credential resolver. Never
    serialize this context into browser payloads, jobs, logs or provider metadata;
    jobs should carry only IDs and resolve fresh credentials when they run.
    """

    connection_id: str | None
    provider: str
    actor_id: str | None = None
    endpoint_id: str | None = None
    authorization_id: str | None = None
    credentials: Mapping[str, str] = field(
        default_factory=dict, repr=False, compare=False
    )
    settings: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class IMIdentityData:
    """Represent a messaging identity without requiring a CRM contact record.

    external_id is an opaque addressable identity within the connection; address
    is a display value and must not be treated as a universal identity key.
    """

    external_id: str
    display_name: str
    address: str = ""
    avatar_url: str = ""
    kind: Literal["person", "channel"] = "person"


@dataclass(frozen=True)
class IMRecipientPage:
    """Return one page of provider identities with an opaque continuation cursor."""

    items: tuple[IMIdentityData, ...] = ()
    next_cursor: str | None = None


@dataclass(frozen=True)
class IMMessageReference:
    """Keep local and external IDs distinct for quotes and thread roots."""

    message_id: str
    provider_message_id: str | None = None


@dataclass(frozen=True)
class IMAttachmentReference:
    """Reference authorized FileNode storage; never embed binaries or signed URLs."""

    file_id: str
    filename: str
    content_type: str
    size: int


@dataclass(frozen=True)
class IMOutboundMessage:
    """Describe one persisted send, with independent quote and thread references.

    The service validates membership, reference scope and file access first.
    idempotency_key stays stable across delivery attempts. recipient_user_ids
    contains only service-authorized internal notification recipients.
    """

    message_id: str
    conversation_id: str
    idempotency_key: str
    sender_id: str
    body: str
    recipient: str | None = None
    provider_conversation_id: str | None = None
    recipient_user_ids: tuple[str, ...] = ()
    reply_to: IMMessageReference | None = None
    thread_root: IMMessageReference | None = None
    attachments: tuple[IMAttachmentReference, ...] = ()
    template_name: str | None = None
    body_html: str = ""


@dataclass(frozen=True)
class IMDeliveryResult:
    """Acknowledge transport acceptance, never imply recipient delivery or reading."""

    provider_message_id: str | None = None
    provider_conversation_id: str | None = None
    status: Literal["accepted"] = "accepted"


@dataclass(frozen=True)
class IMConnectionValidation:
    """Report a real connection check separately from configuration completeness."""

    valid: bool
    capabilities: IMCapabilities
    issues: tuple[str, ...] = ()
    account_display_name: str = ""


@dataclass(frozen=True)
class IMProviderEvent:
    """Normalize inbound data for service-owned persistence and reconciliation.

    event_id is a connection-scoped deduplication key, not just a message ID:
    distinct status transitions on the same message must remain distinct events.
    No credentials or raw webhook bodies belong in this DTO.
    """

    event_id: str
    kind: Literal["message", "status", "identity_upsert", "identity_delete"]
    occurred_at: datetime
    endpoint_id: str | None = None
    provider_message_id: str | None = None
    provider_conversation_id: str | None = None
    sender: IMIdentityData | None = None
    body: str = ""
    reply_to_provider_id: str | None = None
    thread_root_provider_id: str | None = None
    status: Literal["sent", "delivered", "read", "failed"] | None = None


class BaseIMAdapter(ABC):
    """Define transport and directory boundaries without message persistence or Inbox calls."""

    provider_key: str

    def __init__(self, context: IMConnectionContext) -> None:
        """Bind this adapter to exactly one provider connection and authorization."""
        if context.provider != self.provider_key:
            raise ValueError("The connection provider does not match this adapter.")
        self.context = context

    @abstractmethod
    def validate_connection(self) -> IMConnectionValidation:
        """Check actual transport access and return effective account capabilities."""
        raise NotImplementedError

    @abstractmethod
    def send_message(self, message: IMOutboundMessage) -> IMDeliveryResult:
        """Dispatch a committed message once; the service schedules safe retries."""
        raise NotImplementedError

    def format_message(self, message: IMOutboundMessage) -> str:
        """Return the default plain-text transport body without changing stored HTML."""
        return message.body

    def discover_recipients(
        self, query: str, *, cursor: str | None = None, limit: int = 25
    ) -> IMRecipientPage:
        """Discover recipients only where a provider exposes a remote directory.

        The native directory is available to active staff independently of user
        policies. CRM search remains permission-filtered; synchronized identities
        are stored by the service. Other adapters must not scan unfiltered records.
        """
        raise IMUnsupportedOperation("This adapter has no remote recipient directory.")

    def request_contact_sync(self) -> None:
        """Request provider contact synchronization; identities arrive as events."""
        raise IMUnsupportedOperation("This connection does not support contact sync.")

    def receive_events(
        self, body: bytes, headers: Mapping[str, str]
    ) -> tuple[IMProviderEvent, ...]:
        """Verify raw bytes/signature and replay limits before parsing any events.

        Implementations must reject invalid authentication before normalization.
        Webhook challenge handshakes and HTTP responses belong to the endpoint.
        """
        raise IMUnsupportedOperation("This adapter does not accept provider webhooks.")


class IMConnectionConfiguration(BaseModel):
    """Describe provider setup fields used by the shared connection wizard."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255, title="Connection name")

    def external_account_id(self) -> str:
        """Return an optional remote account identifier for this configuration."""
        return ""


@dataclass(frozen=True)
class IMSelectionOption:
    """Carry an opaque selection value with a visible label and optional address."""

    value: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class IMSelectionPage:
    """Return bounded selection options and a provider-owned continuation cursor."""

    items: tuple[IMSelectionOption, ...] = ()
    next_cursor: str | None = None


type IMSelectionResolver = Callable[
    ["AbstractBloomerpUser", dict[str, str], str, str], IMSelectionPage
]
type IMStartHandler = Callable[
    ["AbstractBloomerpUser", dict[str, str]], "IMConversation"
]


class IMConversationActions(TypedDict, total=False):
    """Describe composer availability and optional calling controls for a conversation."""

    can_send: Required[bool]
    can_call: bool
    business_number: str


type IMActionsResolver = Callable[
    ["AbstractBloomerpUser", "IMConversation"], IMConversationActions
]
type IMIdentityLabelResolver = Callable[["IMIdentity", int | UUID], str]
type IMTimelineResolver = Callable[
    ["AbstractBloomerpUser", "IMConversation"], Iterable["BloomerpModel"]
]
type IMCreationHandler = Callable[
    [HttpRequest, "IMProviderDefinition", "IMCreationAction"], HttpResponse
]
type IMPermissionResolver = Callable[[HttpRequest], bool]


class IMSendHandler(Protocol):
    """Define the keyword-capable contract for provider-owned message submission."""

    def __call__(
        self,
        user: AbstractBloomerpUser,
        conversation_id: UUID,
        html: str,
        client_id: str,
        **kwargs: Any,
    ) -> IMMessage:
        """Send validated editor content through the provider's authorized transport."""
        ...


@dataclass(frozen=True)
class IMSelectionStep:
    """Declare a dependent selection resolved server-side by a typed function."""

    key: str
    label: str
    resolver: IMSelectionResolver | str
    searchable: bool = False


@dataclass(frozen=True)
class IMTimelineSource:
    """Register a separate activity source and its shared timeline renderer."""

    resolver: IMTimelineResolver | str
    template: str


@dataclass(frozen=True)
class IMCreationAction:
    """Declare a provider-owned creation flow and its server-side authorization check."""

    key: str
    label: str
    icon: str
    handler: IMCreationHandler | str
    permission_resolver: IMPermissionResolver | str


@dataclass(frozen=True)
class IMProviderDefinition:
    """Declare static provider branding, adapter type and setup requirements.

    planned_capabilities describes design intent for draft adapters. A UI must
    use validate_connection().capabilities for a real connected account.
    Credentials and app signing secrets never belong in definition instances.
    """

    key: str
    display_name: str
    icon: str
    address_field: str
    adapter_class: type[BaseIMAdapter]
    description: str = ""
    auth_mode: Literal["internal", "embedded_signup", "oauth"] = "internal"
    planned_capabilities: IMCapabilities = field(default_factory=IMCapabilities)
    selection_steps: tuple[IMSelectionStep, ...] = ()
    creation_actions: tuple[IMCreationAction, ...] = ()
    start_handler: IMStartHandler | str = ""
    send_handler: IMSendHandler | str = ""
    actions_resolver: IMActionsResolver | str = ""
    identity_label_resolver: IMIdentityLabelResolver | str = ""
    timeline_sources: tuple[IMTimelineSource, ...] = ()
    internal: bool = False
    transport_ready: bool = False
    config_schema: type[IMConnectionConfiguration] = IMConnectionConfiguration

    def resolve_identity(self, identity: Mapping[str, str]) -> dict[str, str]:
        """Resolve UI identity fields with provider-specific address fallback."""
        address = identity.get(self.address_field, "")
        return {
            "displayName": identity.get("name") or address,
            "avatar": identity.get("avatar", ""),
            "address": address,
        }

    def create_adapter(self, context: IMConnectionContext) -> BaseIMAdapter:
        """Instantiate the declared adapter with server-resolved connection context."""
        return self.adapter_class(context)


INSTANT_MESSAGING = InboxFolderTypeDefinition(
    key="instant_messaging",
    name="Messages",
    description="Contains conversations",
    default_sources=[
        InboxEventSource(
            key="im.conversation.activity",
            folder_qs_resolver="bloomerp.communication.builtins.instant_messaging.inbox_source.resolve_conversation_folders",
            handler="bloomerp.communication.builtins.instant_messaging.inbox_source.handle_conversation_activity",
            run_async=False,
        )
    ],
    icon="fa fa-message",
    is_default=True,
    item_type=InboxItemTypeDefinition(
        key="instant_messaging_item",
        name="Conversation",
        name_plural="Conversations",
        icon="fa fa-message",
        source_model="bloomerp.IMConversation",
        on_render=render_inbox_conversation,
        on_mark_as_read=None,
    ),
)
