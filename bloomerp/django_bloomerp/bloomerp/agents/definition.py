"""Version-one JSON contracts for durable agent persistence.

These schemas describe storage, not authorization or tool execution. Runtime and
provider-specific objects are restricted to JSON values and validated by their
registered adapters at execution time. Add a new schema version for breaking changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Literal, Protocol, Self, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile
    from django.http import HttpRequest
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    field_validator,
    model_validator,
)


class AgentPayload(BaseModel):
    """Reject unknown fields and non-finite numbers in structured payloads."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class JsonObject(RootModel[dict[str, JsonValue]]):
    """Carry adapter-owned JSON objects without accepting arbitrary Python objects."""


class TextBlock(AgentPayload):
    """Store explicitly formatted text; HTML sanitization belongs at ingestion."""

    type: Literal["text"] = "text"
    format: Literal["plain", "html", "markdown"] = "plain"
    text: str


class ArtifactBlock(AgentPayload):
    """Locate an artifact through the message's ordered attachment relation."""

    type: Literal["artifact"] = "artifact"
    position: int = Field(ge=0)


class ApprovalBlock(AgentPayload):
    """Reference a persisted approval card in the conversation."""

    type: Literal["approval"] = "approval"
    approval_id: UUID


class MessageContent(
    RootModel[
        list[
            Annotated[
                TextBlock | ArtifactBlock | ApprovalBlock, Field(discriminator="type")
            ]
        ]
    ]
):
    """Validate ordered, typed message blocks independently of an LLM provider."""


class BrowserContext(AgentPayload):
    """Capture optional origin metadata, never a trusted authorization context."""

    instance_origin: str | None = None
    tab_id: UUID | None = None
    page_id: str | None = None
    route_name: str | None = None
    object_id: str | None = None
    form_id: str | None = None
    form_revision: int | None = Field(default=None, ge=0)


class AgentConfigSnapshot(AgentPayload):
    """Record resolved execution settings; credentials must remain outside storage."""

    runtime: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    # Legacy snapshot key identifies the configured AIAgent; preserve it for resumable runs.
    model_record_id: str | None = None
    base_url: str | None = None
    request_timeout_seconds: float = Field(default=60, gt=0)
    instructions: str = ""
    approval_rules: dict[str, JsonValue] = Field(default_factory=dict)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class RunBudgets(AgentPayload):
    """Bound cumulative execution across every attempt of a run."""

    max_tokens: int | None = Field(default=None, gt=0)
    max_tool_calls: int | None = Field(default=None, gt=0)
    max_duration_seconds: int | None = Field(default=None, gt=0)


class RunUsage(AgentPayload):
    """Record aggregate usage across resumes and retries."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    duration_seconds: float = Field(default=0, ge=0)


class AgentError(AgentPayload):
    """Store a safe, structured failure without requiring a traceback."""

    code: str = Field(min_length=1)
    message: str
    retryable: bool = False
    details: dict[str, JsonValue] = Field(default_factory=dict)


class WaitCondition(AgentPayload):
    """Describe a durable external wake condition."""

    kind: Literal["approval", "timer", "external_event", "user_input"]
    approval_ids: list[UUID] = Field(default_factory=list)
    event_key: str | None = None


class ProposalSnapshot(AgentPayload):
    """Bind approval to a versioned tool and its exact validated arguments.

    Browser targets, expected object revisions, and artifact revision IDs belong
    inside arguments so they are included in the proposal fingerprint.
    """

    tool_identifier: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    arguments: dict[str, JsonValue]


class ApprovalRequirement(AgentPayload):
    """Snapshot the server-side rule determining approval eligibility."""

    rule_key: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    mode: Literal["conversation_owner", "assigned_user", "policy"]
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class FileArtifactPayload(AgentPayload):
    """Describe a binary artifact whose content lives in the existing File model."""

    kind: Literal["file"] = "file"
    title: str = ""
    media_type: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class AnalyticsArtifactPayload(AgentPayload):
    """Store analytics configuration using the existing tile validation contract."""

    kind: Literal["analytics"] = "analytics"
    config: dict[str, JsonValue]
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Validate lazily to avoid importing the model graph during app loading."""
        from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig

        return AnalyticsTileConfig.model_validate(value).model_dump(mode="json")


class FormValuePatch(AgentPayload):
    """Describe a proposed field update compatible with behavior value updates."""

    field: str = Field(min_length=1)
    value: JsonValue


class FormPatchArtifactPayload(AgentPayload):
    """Persist a revision-bound draft proposal without authorizing its application."""

    kind: Literal["form_patch"] = "form_patch"
    target_model: str = Field(min_length=1)
    form_id: str = Field(min_length=1)
    object_id: str | None = None
    tab_id: UUID
    page_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    values: list[FormValuePatch] = Field(min_length=1)
    source_artifact_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_fields(self) -> Self:
        """Reject ambiguous proposals containing multiple writes to the same field."""
        names = [patch.field for patch in self.values]
        if len(names) != len(set(names)):
            raise ValueError("A form patch must contain unique field names")
        return self


class ArtifactPayload(
    RootModel[
        Annotated[
            FileArtifactPayload | AnalyticsArtifactPayload | FormPatchArtifactPayload,
            Field(discriminator="kind"),
        ]
    ]
):
    """Dispatch version-one artifact validation by its explicit kind."""


class RunEventPayload(AgentPayload):
    """Carry event references and adapter-specific JSON details for replay."""

    message_id: UUID | None = None
    tool_call_id: UUID | None = None
    approval_id: UUID | None = None
    artifact_id: UUID | None = None
    text: str | None = None
    data: dict[str, JsonValue] = Field(default_factory=dict)


class AIArtifactPayload(AgentPayload):
    """Base for registered artifact payloads; references do not grant access."""


class AIArtifactDescription(AgentPayload):
    """Lightweight context for the LLM, without fetching or analyzing content."""

    title: str
    summary: str


class AIArtifactSearchRequest(AgentPayload):
    """Bound a context-picker search; authorization comes from the HTTP request."""

    query: str = Field(default="", max_length=255)
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class AIArtifactSearchPage[ArtifactPayloadT: AIArtifactPayload](AgentPayload):
    """Return authorized candidate payloads without creating persisted artifacts."""

    items: list[ArtifactPayloadT] = Field(default_factory=list)
    cursor: str | None = None


class AIArtifactRenderer[ArtifactPayloadT: AIArtifactPayload](ABC):
    """Render an authorized artifact as a server-generated component fragment."""

    @classmethod
    @abstractmethod
    def render(
        cls, artifact_id: UUID, payload: ArtifactPayloadT, request: HttpRequest
    ) -> str:
        """Render content and recheck target access before reading live data."""
        raise NotImplementedError


class AIArtifactCandidate(AgentPayload):
    """A type-local proposal; the host supplies conversation and provenance."""

    key: str = Field(min_length=1, max_length=255)
    payload: dict[str, JsonValue]
    display: bool = True
    file_id: UUID | None = None


class AIArtifactToolResult(AgentPayload):
    """Provide an adapter the unchanged MCP result and its originating arguments."""

    tool_name: str
    arguments: dict[str, JsonValue]
    result: dict[str, JsonValue]


class AIArtifactToolResultAdapter(ABC):
    """Translate successful tool results without executing or retrying the tool."""

    key: str
    tool_names: tuple[str, ...]

    @classmethod
    @abstractmethod
    def adapt(
        cls, result: AIArtifactToolResult, request: HttpRequest
    ) -> list[AIArtifactCandidate]:
        """Return authorized artifact candidates, or none for irrelevant results."""
        raise NotImplementedError


@runtime_checkable
class AIArtifactAuthorizer[ArtifactPayloadT: AIArtifactPayload](Protocol):
    """Check current source access without importing Django into runtime contracts."""

    def __call__(self, payload: ArtifactPayloadT, request: HttpRequest) -> None:
        """Raise permission denied when the actor cannot read the referenced source."""
        ...


@runtime_checkable
class AIArtifactSearch[ArtifactPayloadT: AIArtifactPayload](Protocol):
    """Discover bounded authorized candidates for the attachment menu."""

    def __call__(
        self, request: HttpRequest, search: AIArtifactSearchRequest
    ) -> AIArtifactSearchPage[ArtifactPayloadT]:
        """Return a page of candidates without persisting or analyzing them."""
        ...


@runtime_checkable
class AIArtifactUpload[ArtifactPayloadT: AIArtifactPayload](Protocol):
    """Create an authorized binary source and return its attachable payload."""

    def __call__(self, request: HttpRequest, file: UploadedFile) -> ArtifactPayloadT:
        """Validate and store one upload using the application's file lifecycle."""
        ...


class AIArtifactTypeDefinition[ArtifactPayloadT: AIArtifactPayload](BaseModel):
    """Define validation and optional presentation/discovery, never tool execution."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    schema_version: int = Field(default=1, ge=1)
    label: str
    model: type[ArtifactPayloadT]
    describe: Callable[[ArtifactPayloadT], AIArtifactDescription]
    authorize: AIArtifactAuthorizer[ArtifactPayloadT] | None = None
    icon: str | None = None
    render_cls: type[AIArtifactRenderer] | None = None
    search: AIArtifactSearch[ArtifactPayloadT] | None = None
    upload: AIArtifactUpload[ArtifactPayloadT] | None = None
    selection_file_id: Callable[[ArtifactPayloadT], UUID | None] | None = None
    tool_names: tuple[str, ...] = ()
    tool_result_adapters: tuple[type[AIArtifactToolResultAdapter], ...] = ()


PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "object.v1": JsonObject,
    "message.v1": MessageContent,
    "browser.v1": BrowserContext,
    "config.v1": AgentConfigSnapshot,
    "budgets.v1": RunBudgets,
    "usage.v1": RunUsage,
    "error.v1": AgentError,
    "wait.v1": WaitCondition,
    "proposal.v1": ProposalSnapshot,
    "approval_requirement.v1": ApprovalRequirement,
    "artifact.v1": ArtifactPayload,
    "event.v1": RunEventPayload,
}
