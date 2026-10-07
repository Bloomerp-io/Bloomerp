"""Provider-independent contracts and shared execution for agent runtimes.

The runner owns persistence, leases, event sequencing, budgets, and delivery. An
adapter owns model interaction and versioned provider history. Every tool call
must pass through the supplied coordinator, which uses the existing MCP tool
implementations and enforces authorization, approvals, and effect idempotency.

AgentRuntime defines the public protocol; BaseAgentRuntime supplies the shared
execution lifecycle and abstract adapter hooks. Persisted JSON schemas remain in
definition.py. This module imports no Django models, SDKs, or worker integrations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from time import monotonic
from typing import Annotated, Literal, Protocol, Self, runtime_checkable
from urllib.parse import urlsplit
from uuid import UUID

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from jsonschema.validators import validator_for
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    model_validator,
)

from bloomerp.agents.definition import (
    AgentConfigSnapshot,
    AgentError,
    BrowserContext,
    RunBudgets,
    RunUsage,
    TextBlock,
    WaitCondition,
)


class AgentRuntimePayload(BaseModel):
    """Validate portable runtime data while rejecting misspelled contract fields."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AgentRuntimeConfig(AgentConfigSnapshot):
    """Resolve non-secret instance settings and pin them for the entire run.

    Provider/model identifiers remain open strings for custom integrations.
    Parameters are provider-specific; adapters must validate supported options.
    No API keys, authorization headers, or credential-bearing URLs belong here.
    """

    agent_key: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)

    def to_snapshot(self) -> AgentConfigSnapshot:
        """Build AIRun.config_snapshot; agent key/version use separate model fields."""
        return AgentConfigSnapshot.model_validate(
            self.model_dump(mode="json", exclude={"agent_key", "agent_version"})
        )

    def fingerprint(self) -> str:
        """Identify the exact resolved configuration when checking checkpoint reuse."""
        encoded = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class AgentRuntimeCredentials(AgentRuntimePayload):
    """Supply secrets explicitly at execution time, excluded from repr and dumps.

    The instance's secret resolver supplies the current key on every attempt, so
    credentials can rotate without changing the run's model configuration.
    """

    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    provider_credentials: BaseModel | None = Field(default=None, exclude=True, repr=False)


class AgentRuntimeContext(AgentRuntimePayload):
    """Bind execution to a server-authorized actor and optional browser origin."""

    user_id: str = Field(min_length=1)
    conversation_id: UUID
    origin_browser_context: BrowserContext | None = None


class AgentRuntimeArtifactInput(AgentRuntimePayload):
    """Carry an authorized artifact revision resolved by the context builder.

    Content contains model-readable structured data or extracted text. File URI
    is optional for supported multimodal providers and must be refreshed when
    expired. User documents remain input data, never trusted system instructions.
    """

    type: Literal["artifact"] = "artifact"
    artifact_id: UUID
    media_type: str | None = None
    file_uri: str | None = None
    content: dict[str, JsonValue] = Field(default_factory=dict)


class AgentRuntimeToolCallInput(AgentRuntimePayload):
    """Preserve an earlier assistant tool request and its provider call identity."""

    type: Literal["tool_call"] = "tool_call"
    provider_call_id: str = Field(min_length=1)
    tool_identifier: str = Field(min_length=1)
    arguments: dict[str, JsonValue]


class AgentRuntimeToolResultInput(AgentRuntimePayload):
    """Pair a previous tool result with its original provider call identifier."""

    type: Literal["tool_result"] = "tool_result"
    provider_call_id: str = Field(min_length=1)
    result: dict[str, JsonValue]
    is_error: bool = False


type AgentRuntimeInputBlock = Annotated[
    TextBlock
    | AgentRuntimeArtifactInput
    | AgentRuntimeToolCallInput
    | AgentRuntimeToolResultInput,
    Field(discriminator="type"),
]


class AgentRuntimeMessage(AgentRuntimePayload):
    """Provide structured model input rather than a persisted UI message.

    The context builder resolves attachment positions into artifact inputs and
    removes UI-only approval cards. Tool history can be synthesized from stored
    calls. Opaque reasoning/provider continuation data belongs in checkpoints.
    """

    role: Literal["user", "assistant", "system", "tool"]
    content: tuple[AgentRuntimeInputBlock, ...]
    message_id: UUID | None = None
    sequence: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_source_and_roles(self) -> Self:
        """Keep transcript provenance paired and tool blocks in appropriate roles."""
        if (self.message_id is None) != (self.sequence is None):
            raise ValueError(
                "Message ID and transcript sequence must be supplied together"
            )
        for block in self.content:
            if block.type == "tool_call" and self.role != "assistant":
                raise ValueError("Tool-call input belongs to an assistant message")
            if block.type == "tool_result" and self.role != "tool":
                raise ValueError("Tool-result input belongs to a tool message")
            if self.role == "tool" and block.type != "tool_result":
                raise ValueError("Tool messages must contain only tool results")
        return self


class AgentRuntimeToolDefinition(AgentRuntimePayload):
    """Describe a permission-filtered MCP tool without embedding executable code."""

    identifier: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue] | None = None
    title: str | None = None
    annotations: dict[str, bool] = Field(default_factory=dict)


class AgentRuntimeRunRequest(AgentRuntimePayload):
    """Start one execution attempt with resolved settings and bounded context.

    On execute, messages contain initial model context. On resume, messages contain
    only new transcript entries after the checkpoint cursor; saved adapter history
    is restored from the checkpoint. Usage is cumulative across earlier attempts.
    Tools are rediscovered under current permissions on every attempt.
    """

    run_id: UUID
    attempt_id: UUID
    config: AgentRuntimeConfig
    context: AgentRuntimeContext
    messages: tuple[AgentRuntimeMessage, ...] = ()
    tools: tuple[AgentRuntimeToolDefinition, ...] = ()
    budgets: RunBudgets = Field(default_factory=RunBudgets)
    usage: RunUsage = Field(default_factory=RunUsage)

    @model_validator(mode="after")
    def validate_catalog_and_order(self) -> Self:
        """Reject ambiguous tool identifiers and unordered transcript entries."""
        identifiers = [tool.identifier for tool in self.tools]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Tool identifiers must be unique")
        sequences = [
            message.sequence
            for message in self.messages
            if message.sequence is not None
        ]
        if sequences != sorted(set(sequences)):
            raise ValueError("Transcript sequences must be unique and increasing")
        return self


class AgentRuntimeCheckpoint(AgentRuntimePayload):
    """Save opaque provider history at a safe adapter execution boundary.

    The runner stores this envelope in AIRun.checkpoint, with runtime and format
    version also mirrored into the corresponding model fields. SDK objects,
    credentials, and executable Python objects must never enter state. Adapters
    must preserve provider continuation/reasoning items needed for exact replay.
    """

    run_id: UUID
    context: AgentRuntimeContext
    runtime: str = Field(min_length=1)
    runtime_version: str = Field(min_length=1)
    format_version: int = Field(default=1, ge=1)
    config_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumed_message_sequence: int = Field(default=0, ge=0)
    pending_tool_call_ids: tuple[UUID, ...] = ()
    state: dict[str, JsonValue]

    @model_validator(mode="after")
    def unique_pending_calls(self) -> Self:
        """Reject duplicate pending action identities before attempting a resume."""
        if len(self.pending_tool_call_ids) != len(set(self.pending_tool_call_ids)):
            raise ValueError("Pending tool call IDs must be unique")
        return self


class AgentRuntimeResumeRequest(AgentRuntimePayload):
    """Restore the same logical run under a fresh attempt and current credentials.

    No caller-supplied approval booleans are accepted. The coordinator resolves
    checkpoint.pending_tool_call_ids against persisted approvals and outcomes.
    The adapter must additionally reject unsupported checkpoint/runtime versions.
    """

    run: AgentRuntimeRunRequest
    checkpoint: AgentRuntimeCheckpoint

    @model_validator(mode="after")
    def validate_checkpoint_binding(self) -> Self:
        """Reject cross-run, cross-actor, changed-config, and duplicate-input resumes."""
        if (
            self.checkpoint.run_id != self.run.run_id
            or self.checkpoint.context != self.run.context
        ):
            raise ValueError("Checkpoint must belong to the same run and context")
        if self.checkpoint.runtime != self.run.config.runtime:
            raise ValueError("Checkpoint runtime does not match the selected adapter")
        if self.checkpoint.config_fingerprint != self.run.config.fingerprint():
            raise ValueError("Checkpoint configuration does not match the original run")
        for message in self.run.messages:
            if (
                message.sequence is None
                or message.sequence <= self.checkpoint.consumed_message_sequence
            ):
                raise ValueError(
                    "Resume input must contain only new transcript messages"
                )
        return self


class AgentRuntimeToolProposal(AgentRuntimePayload):
    """Propose a stable provider call to the run-bound coordinator.

    The coordinator resolves the provider call ID within the run to the durable
    AIToolCall and idempotency key. Repeated proposals with changed arguments are
    rejected; completed effects are never blindly re-executed.
    """

    provider_call_id: str = Field(min_length=1)
    tool_identifier: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    arguments: dict[str, JsonValue]


class AgentRuntimeToolOutcome(AgentRuntimePayload):
    """Return a persisted outcome, including a durable approval pause if needed."""

    tool_call_id: UUID
    provider_call_id: str = Field(min_length=1)
    status: Literal["completed", "failed", "rejected", "waiting"]
    result: dict[str, JsonValue] | None = None
    error: AgentError | None = None
    approval_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Require an unambiguous result, failure, or pending approval."""
        if self.status == "waiting":
            if (
                not self.approval_ids
                or self.result is not None
                or self.error is not None
            ):
                raise ValueError(
                    "Waiting outcomes require approval IDs and no result or error"
                )
        elif self.approval_ids:
            raise ValueError("Only waiting outcomes may contain pending approval IDs")
        if self.status == "completed" and (
            self.result is None or self.error is not None
        ):
            raise ValueError("Completed outcomes require a result and no error")
        if self.status in {"failed", "rejected"} and (
            self.error is None or self.result is not None
        ):
            raise ValueError(
                "Failed or rejected outcomes require an error and no result"
            )
        return self


@runtime_checkable
class AgentRuntimeToolCoordinator(Protocol):
    """Coordinate existing MCP tools for one server-bound run and attempt.

    Implementations authenticate the bound actor, check the current worker lease,
    revalidate tool arguments and permissions, persist before executing effects,
    and own approval eligibility and idempotent result reconciliation. No tool
    implementation or independent MCP client may bypass this boundary.
    """

    async def call(self, proposal: AgentRuntimeToolProposal) -> AgentRuntimeToolOutcome:
        """Record a proposal and return an existing result, execute it, or defer it."""
        ...

    async def resolve(self, tool_call_id: UUID) -> AgentRuntimeToolOutcome:
        """Recheck persisted approvals/results for a pending call belonging to this run."""
        ...


class AgentRuntimeEventBase(AgentRuntimePayload):
    """Identify an event's logical run and executor for runner-side lease fencing."""

    run_id: UUID
    attempt_id: UUID


class AgentRuntimeTextDeltaEvent(AgentRuntimeEventBase):
    """Append visible output to a stable message/block within this attempt."""

    kind: Literal["text.delta"] = "text.delta"
    message_id: UUID
    block_index: int = Field(ge=0)
    format: Literal["plain", "html", "markdown"] = "plain"
    text: str


class AgentRuntimeToolOutcomeEvent(AgentRuntimeEventBase):
    """Report a coordinator-owned action outcome without executing effects twice."""

    kind: Literal["tool.outcome"] = "tool.outcome"
    outcome: AgentRuntimeToolOutcome


class AgentRuntimeToolStartedEvent(AgentRuntimeEventBase):
    """Announce a persisted tool that has passed approval and is about to execute."""

    kind: Literal["tool.started"] = "tool.started"
    tool_call_id: UUID


class AgentRuntimeArtifactCreatedEvent(AgentRuntimeEventBase):
    """Reference an artifact already persisted by an authorized tool operation."""

    kind: Literal["artifact.created"] = "artifact.created"
    artifact_id: UUID


class AgentRuntimeUsageUpdatedEvent(AgentRuntimeEventBase):
    """Report usage accumulated during this attempt, not lifetime totals."""

    kind: Literal["usage.updated"] = "usage.updated"
    usage: RunUsage


class AgentRuntimeCheckpointEventBase(AgentRuntimeEventBase):
    """Share validated checkpoint ownership across checkpoint and pause events."""

    checkpoint: AgentRuntimeCheckpoint

    @model_validator(mode="after")
    def validate_checkpoint_run(self) -> Self:
        """Prevent an event from carrying another run's checkpoint."""
        if self.checkpoint.run_id != self.run_id:
            raise ValueError("Event and checkpoint must belong to the same run")
        return self


class AgentRuntimeCheckpointEvent(AgentRuntimeCheckpointEventBase):
    """Offer a checkpoint which the runner commits before consuming further events."""

    kind: Literal["checkpoint.created"] = "checkpoint.created"


class AgentRuntimeRunPausedEvent(AgentRuntimeCheckpointEventBase):
    """End this attempt with a durable checkpoint and a condition for resumption."""

    kind: Literal["run.paused"] = "run.paused"
    wait_condition: WaitCondition
    usage: RunUsage
    resume_after: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_wake_condition(self) -> Self:
        """Require scheduling data for timers and durable references for approval waits."""
        if self.wait_condition.kind == "timer" and self.resume_after is None:
            raise ValueError("Timer pauses require an aware resume_after timestamp")
        if self.wait_condition.kind == "approval" and (
            not self.wait_condition.approval_ids
            or not self.checkpoint.pending_tool_call_ids
        ):
            raise ValueError(
                "Approval pauses require approval IDs and pending tool calls"
            )
        return self


class AgentRuntimeRunFinishedEvent(AgentRuntimeEventBase):
    """Terminate an attempt by completing or cancelling its logical run."""

    kind: Literal["run.completed", "run.cancelled"]
    usage: RunUsage


class AgentRuntimeRunFailedEvent(AgentRuntimeEventBase):
    """Report a classified failure for runner-owned retry or terminal handling."""

    kind: Literal["run.failed"] = "run.failed"
    error: AgentError
    usage: RunUsage


type AgentRuntimeEvent = Annotated[
    AgentRuntimeTextDeltaEvent
    | AgentRuntimeToolStartedEvent
    | AgentRuntimeToolOutcomeEvent
    | AgentRuntimeArtifactCreatedEvent
    | AgentRuntimeUsageUpdatedEvent
    | AgentRuntimeCheckpointEvent
    | AgentRuntimeRunPausedEvent
    | AgentRuntimeRunFinishedEvent
    | AgentRuntimeRunFailedEvent,
    Field(discriminator="kind"),
]


@runtime_checkable
class AgentRuntime(Protocol):
    """Adapt an agent framework without owning Django state or scheduling.

    execute/resume return async iterators directly (not awaitable iterators).
    Yield exactly one final run.paused/completed/failed/cancelled event on a normal
    stream exit. Unexpected exceptions or interruption remain recoverable by the
    runner; adapters must not fabricate successful completion. Closing an iterator
    releases its resources and must not leave background tool execution running.

    Checkpoint before deferring approvals. On resume, restore adapter history and
    resolve every pending call through the coordinator before continuing. Usage
    events and terminal usage are cumulative within the attempt; the runner must
    replace attempt totals rather than summing repeated snapshots. The runner
    fences events by attempt ID and persists before broadcasting to the browser.
    """

    def validate_request(self, request: AgentRuntimeRunRequest) -> None:
        """Reject unsupported provider settings, modalities, tools, or limits before effects."""
        ...

    def execute(
        self,
        request: AgentRuntimeRunRequest,
        *,
        credentials: AgentRuntimeCredentials,
        coordinator: AgentRuntimeToolCoordinator,
    ) -> AsyncIterator[AgentRuntimeEvent]:
        """Start a validated attempt using explicit instance credentials and gated tools."""
        ...

    def resume(
        self,
        request: AgentRuntimeResumeRequest,
        *,
        credentials: AgentRuntimeCredentials,
        coordinator: AgentRuntimeToolCoordinator,
    ) -> AsyncIterator[AgentRuntimeEvent]:
        """Restore compatible state and recheck durable tool outcomes under a fresh lease."""
        ...

    async def cancel(self, run_id: UUID, *, attempt_id: UUID) -> None:
        """Idempotently request local cancellation of this exact attempt.

        The service also persists cancel_requested_at for workers in other
        processes. Cancellation cannot undo effects that already completed.
        """
        ...

    async def aclose(self) -> None:
        """Release adapter-owned clients and resources at the end of its service lifetime."""
        ...


class AgentRuntimeBudgetExceeded(Exception):
    """Signal exhaustion of a framework-neutral execution budget."""


class AgentRuntimePendingToolProposal(AgentRuntimePayload):
    """Retain a proposal and its coordinator outcome or pre-dispatch validation error."""

    proposal: AgentRuntimeToolProposal
    outcome: AgentRuntimeToolOutcome | None = None
    validation_error: AgentError | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        """Keep pre-dispatch validation failures separate from executed tool outcomes."""
        if self.outcome is not None and self.validation_error is not None:
            raise ValueError(
                "A proposal cannot have both an outcome and a validation error"
            )
        return self


class AgentRuntimeState(AgentRuntimePayload):
    """Carry shared continuation fields alongside an adapter's serialized history."""

    pending: list[AgentRuntimePendingToolProposal] = Field(default_factory=list)
    consumed_sequence: int = Field(default=0, ge=0)
    finished: bool = False


def _event_queue() -> asyncio.Queue[AgentRuntimeEvent]:
    """Create a bounded delivery channel for one active attempt."""
    return asyncio.Queue(1)


@dataclass
class AgentRuntimeAttempt:
    """Keep live cancellation, backpressure, and portable usage outside checkpoints."""

    request: AgentRuntimeRunRequest
    queue: asyncio.Queue[AgentRuntimeEvent] = field(default_factory=_event_queue)
    acknowledged: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    abandoned: bool = False
    producer_started: bool = False
    cancellation_requested: bool = False
    started: float = field(default_factory=monotonic)
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0

    def record_tokens(self, *, input_tokens: int, output_tokens: int) -> None:
        """Retain cumulative attempt usage, including observations from partial streams."""
        self.input_tokens = max(self.input_tokens, input_tokens)
        self.output_tokens = max(self.output_tokens, output_tokens)

    def usage(self) -> RunUsage:
        """Report this attempt's totals without recounting previous attempts."""
        return RunUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            tool_calls=self.tool_calls,
            duration_seconds=max(0, monotonic() - self.started),
        )

    async def emit(self, event: AgentRuntimeEvent) -> None:
        """Wait for the runner to commit each event before allowing further work."""
        self.acknowledged.clear()
        await self.queue.put(event)
        if event.kind not in {
            "run.completed",
            "run.failed",
            "run.cancelled",
            "run.paused",
        }:
            await self.acknowledged.wait()


class BaseAgentRuntime[StateT: AgentRuntimeState](AgentRuntime, ABC):
    """Implement the shared runtime contract with typed framework-specific hooks.

    Adapters call _save before effects and _dispatch to reconcile proposed tools.
    The runner still owns persistence, distributed leases, and event publication.
    _run must release its resources before returning its single terminal event.
    """

    def __init__(self) -> None:
        """Initialize process-local attempt tracking without allocating SDK resources."""
        self._attempts: dict[tuple[UUID, UUID], AgentRuntimeAttempt] = {}
        self._closed = False

    @property
    @abstractmethod
    def runtime_name(self) -> str:
        """Identify the adapter in configuration and checkpoint envelopes."""
        ...

    @property
    @abstractmethod
    def runtime_version(self) -> str:
        """Identify the adapter's supported checkpoint semantics."""
        ...

    def validate_request(self, request: AgentRuntimeRunRequest) -> None:
        """Validate common execution settings before invoking adapter-specific checks."""
        if self._closed:
            raise ValueError("Runtime is closed")
        if request.config.runtime != self.runtime_name:
            raise ValueError(f"Runtime must be {self.runtime_name}")
        if request.config.base_url:
            url = urlsplit(request.config.base_url)
            if (
                url.scheme not in {"https", "http"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError(
                    "Provider base_url must be an HTTP endpoint without credentials or query parameters"
                )
        for tool in request.tools:
            validator_for(tool.input_schema).check_schema(tool.input_schema)
            if tool.input_schema.get("type") != "object":
                raise ValueError("Tool input schemas must describe an object")
        self._validate_request(request)

    @abstractmethod
    def _validate_request(self, request: AgentRuntimeRunRequest) -> None:
        """Reject unsupported framework settings and input modalities before effects."""
        ...

    @abstractmethod
    def _initial_state(self, request: AgentRuntimeRunRequest) -> StateT:
        """Convert initial portable messages to adapter-specific continuation state."""
        ...

    @abstractmethod
    def _restore_state(self, checkpoint: AgentRuntimeCheckpoint) -> StateT:
        """Validate and decode saved adapter history, including its SDK version."""
        ...

    @abstractmethod
    def _add_messages(self, request: AgentRuntimeRunRequest, state: StateT) -> None:
        """Queue new messages without splitting an unresolved provider tool exchange."""
        ...

    def _serialize_state(self, state: StateT) -> dict[str, JsonValue]:
        """Serialize typed continuation data without retaining live mutable references."""
        return state.model_dump(mode="json")

    @abstractmethod
    def _apply_tool_results(self, state: StateT) -> None:
        """Append pending outcomes and validation errors to the framework's history."""
        ...

    @abstractmethod
    async def _run(
        self,
        attempt: AgentRuntimeAttempt,
        state: StateT,
        credentials: AgentRuntimeCredentials,
        coordinator: AgentRuntimeToolCoordinator,
    ) -> AgentRuntimeRunFinishedEvent | AgentRuntimeRunPausedEvent:
        """Execute the framework loop and release owned resources before returning."""
        ...

    def _classify_error(self, error: Exception) -> AgentError:
        """Classify portable failures without persisting potentially secret error text."""
        if isinstance(error, AgentRuntimeBudgetExceeded):
            code, message, retryable = (
                "budget_exceeded",
                "The run's execution budget was exhausted.",
                False,
            )
        elif isinstance(error, TimeoutError):
            code, message, retryable = "timeout", "The agent execution timed out.", True
        else:
            code, message, retryable = (
                "runtime_error",
                "The agent could not continue this attempt.",
                False,
            )
        return AgentError(
            code=code,
            message=message,
            retryable=retryable,
            details={"exception_type": type(error).__name__},
        )

    def execute(
        self,
        request: AgentRuntimeRunRequest,
        *,
        credentials: AgentRuntimeCredentials,
        coordinator: AgentRuntimeToolCoordinator,
    ) -> AsyncIterator[AgentRuntimeEvent]:
        """Validate initial context and start a cancellable execution attempt."""
        self.validate_request(request)
        state = self._initial_state(request)
        state.consumed_sequence = max(
            (message.sequence or 0 for message in request.messages), default=0
        )
        return self._stream(request, state, credentials, coordinator)

    def resume(
        self,
        request: AgentRuntimeResumeRequest,
        *,
        credentials: AgentRuntimeCredentials,
        coordinator: AgentRuntimeToolCoordinator,
    ) -> AsyncIterator[AgentRuntimeEvent]:
        """Restore a compatible checkpoint under a fresh attempt and current settings."""
        self.validate_request(request.run)
        checkpoint = request.checkpoint
        if (
            checkpoint.runtime_version != self.runtime_version
            or checkpoint.format_version != 1
        ):
            raise ValueError("Unsupported runtime checkpoint version")
        state = self._restore_state(checkpoint)
        if state.consumed_sequence != checkpoint.consumed_message_sequence:
            raise ValueError("Checkpoint transcript cursors do not match")
        if self._pending_ids(state) != checkpoint.pending_tool_call_ids:
            raise ValueError("Checkpoint pending tool identities do not match")
        self._add_messages(request.run, state)
        state.consumed_sequence = max(
            [state.consumed_sequence]
            + [message.sequence or 0 for message in request.run.messages]
        )
        return self._stream(request.run, state, credentials, coordinator)

    def _pending_ids(self, state: StateT) -> tuple[UUID, ...]:
        """Read durable call identities still awaiting coordinator approval resolution."""
        return tuple(
            item.outcome.tool_call_id
            for item in state.pending
            if item.outcome is not None and item.outcome.status == "waiting"
        )

    async def _stream(
        self,
        request: AgentRuntimeRunRequest,
        state: StateT,
        credentials: AgentRuntimeCredentials,
        coordinator: AgentRuntimeToolCoordinator,
    ) -> AsyncIterator[AgentRuntimeEvent]:
        """Bridge a cancellable producer to a commit-before-next-event consumer."""
        if self._closed:
            raise ValueError("Runtime is closed")
        key = (request.run_id, request.attempt_id)
        if key in self._attempts:
            raise ValueError("This attempt is already running locally")
        attempt = AgentRuntimeAttempt(request)
        self._attempts[key] = attempt
        attempt.task = asyncio.create_task(
            self._produce(attempt, state, credentials, coordinator)
        )
        try:
            while True:
                event = await attempt.queue.get()
                yield event
                attempt.acknowledged.set()
                if event.kind in {
                    "run.completed",
                    "run.failed",
                    "run.cancelled",
                    "run.paused",
                }:
                    break
        finally:
            attempt.abandoned = True
            if not attempt.task.done():
                attempt.task.cancel()
            with suppress(asyncio.CancelledError):
                await attempt.task
            self._attempts.pop(key, None)

    async def _produce(
        self,
        attempt: AgentRuntimeAttempt,
        state: StateT,
        credentials: AgentRuntimeCredentials,
        coordinator: AgentRuntimeToolCoordinator,
    ) -> None:
        """Own execution tasks and translate terminal failures without leaking secrets."""
        request = attempt.request
        identity = {"run_id": request.run_id, "attempt_id": request.attempt_id}
        attempt.producer_started = True
        deadline: asyncio.Timeout | None = None
        try:
            if attempt.cancellation_requested:
                raise asyncio.CancelledError
            duration = request.budgets.max_duration_seconds
            remaining = (
                None if duration is None else duration - request.usage.duration_seconds
            )
            if remaining is not None and remaining <= 0:
                raise AgentRuntimeBudgetExceeded("Duration budget exhausted")
            deadline = asyncio.timeout(remaining)
            async with deadline:
                terminal = await self._run(attempt, state, credentials, coordinator)
            await attempt.emit(terminal)
        except asyncio.CancelledError:
            if attempt.abandoned:
                raise
            # A queued event may not have been consumed yet; terminal cancellation
            # replaces it, ensuring shutdown cannot block on an absent consumer.
            with suppress(asyncio.QueueEmpty):
                attempt.queue.get_nowait()
            await attempt.queue.put(
                AgentRuntimeRunFinishedEvent(
                    **identity, kind="run.cancelled", usage=attempt.usage()
                )
            )
        except Exception as error:  # noqa: BLE001 - sanitize arbitrary provider/coordinator failures
            if (
                isinstance(error, TimeoutError)
                and deadline is not None
                and deadline.expired()
            ):
                classified = self._classify_error(
                    AgentRuntimeBudgetExceeded("Duration budget exhausted")
                )
            else:
                classified = self._classify_error(error)
            await attempt.queue.put(
                AgentRuntimeRunFailedEvent(
                    **identity,
                    error=classified,
                    usage=attempt.usage(),
                )
            )

    def _checkpoint(
        self, request: AgentRuntimeRunRequest, state: StateT
    ) -> AgentRuntimeCheckpoint:
        """Snapshot the continuation without retaining mutable live state references."""
        return AgentRuntimeCheckpoint(
            run_id=request.run_id,
            context=request.context,
            runtime=self.runtime_name,
            runtime_version=self.runtime_version,
            config_fingerprint=request.config.fingerprint(),
            consumed_message_sequence=state.consumed_sequence,
            pending_tool_call_ids=self._pending_ids(state),
            state=self._serialize_state(state),
        )

    async def _save(self, attempt: AgentRuntimeAttempt, state: StateT) -> None:
        """Expose current usage and checkpoint before any subsequent side effect."""
        identity = {
            "run_id": attempt.request.run_id,
            "attempt_id": attempt.request.attempt_id,
        }
        await attempt.emit(
            AgentRuntimeUsageUpdatedEvent(**identity, usage=attempt.usage())
        )
        await attempt.emit(
            AgentRuntimeCheckpointEvent(
                **identity, checkpoint=self._checkpoint(attempt.request, state)
            )
        )

    @staticmethod
    def _tool_validation_error(error: JsonSchemaValidationError) -> AgentError:
        """Describe a schema failure without echoing argument values or exception text."""
        details: dict[str, JsonValue] = {
            "validator": str(error.validator)[:100],
            "argument_path": [
                str(part)[:100] for part in list(error.absolute_path)[:20]
            ],
            "schema_path": [
                str(part)[:100] for part in list(error.absolute_schema_path)[:20]
            ],
        }
        if isinstance(error.schema, dict):
            properties = error.schema.get("properties")
            if isinstance(properties, dict):
                details["allowed_fields"] = [
                    str(name)[:100] for name in list(properties)[:20]
                ]
            required = error.schema.get("required")
            if isinstance(required, list):
                details["required_fields"] = [str(name)[:100] for name in required[:20]]
            expected_type = error.schema.get("type")
            if isinstance(expected_type, str):
                details["expected_type"] = expected_type[:100]
        return AgentError(
            code="tool_validation_error",
            message="Invalid tool arguments. Correct the call to match the tool's input schema and try again. The tool was not executed.",
            retryable=True,
            details=details,
        )

    async def _dispatch(
        self,
        attempt: AgentRuntimeAttempt,
        state: StateT,
        coordinator: AgentRuntimeToolCoordinator,
    ) -> AgentRuntimeRunPausedEvent | None:
        """Reconcile proposals sequentially and pause if approvals remain outstanding."""
        request = attempt.request
        catalog = {tool.identifier: tool for tool in request.tools}
        for item in state.pending:
            old = item.outcome
            if item.validation_error is not None or (
                old is not None and old.status != "waiting"
            ):
                continue
            proposal = item.proposal
            tool = catalog.get(proposal.tool_identifier)
            if tool is None or tool.version != proposal.tool_version:
                raise ValueError("A pending tool is unavailable or has changed version")
            if old is None:
                limit = request.budgets.max_tool_calls
                if (
                    limit is not None
                    and request.usage.tool_calls + attempt.tool_calls >= limit
                ):
                    raise AgentRuntimeBudgetExceeded("Tool call budget exhausted")
                attempt.tool_calls += 1
                try:
                    validator_for(tool.input_schema)(tool.input_schema).validate(
                        proposal.arguments
                    )
                except JsonSchemaValidationError as error:
                    item.validation_error = self._tool_validation_error(error)
                    await self._save(attempt, state)
                    continue
                outcome = await coordinator.call(proposal)
            else:
                validator_for(tool.input_schema)(tool.input_schema).validate(
                    proposal.arguments
                )
                outcome = await coordinator.resolve(old.tool_call_id)
            if outcome.provider_call_id != proposal.provider_call_id or (
                old is not None and outcome.tool_call_id != old.tool_call_id
            ):
                raise ValueError("Coordinator returned another tool call's outcome")
            item.outcome = outcome
            await self._save(attempt, state)
            await attempt.emit(
                AgentRuntimeToolOutcomeEvent(
                    run_id=request.run_id,
                    attempt_id=request.attempt_id,
                    outcome=outcome,
                )
            )
        waiting = [
            item.outcome
            for item in state.pending
            if item.outcome is not None and item.outcome.status == "waiting"
        ]
        if waiting:
            return AgentRuntimeRunPausedEvent(
                run_id=request.run_id,
                attempt_id=request.attempt_id,
                checkpoint=self._checkpoint(request, state),
                usage=attempt.usage(),
                wait_condition=WaitCondition(
                    kind="approval",
                    approval_ids=list(
                        dict.fromkeys(
                            approval
                            for outcome in waiting
                            for approval in outcome.approval_ids
                        )
                    ),
                ),
            )
        self._apply_tool_results(state)
        state.pending = []
        return None

    async def cancel(self, run_id: UUID, *, attempt_id: UUID) -> None:
        """Cancel only the specified local producer, leaving the consumer task alive."""
        attempt = self._attempts.get((run_id, attempt_id))
        if attempt is not None and attempt.task is not None and not attempt.task.done():
            if not attempt.cancellation_requested:
                attempt.cancellation_requested = True
                if attempt.producer_started:
                    attempt.task.cancel()
            with suppress(asyncio.CancelledError):
                await attempt.task

    async def aclose(self) -> None:
        """Prevent new attempts and unwind every active SDK/client operation."""
        self._closed = True
        for run_id, attempt_id in list(self._attempts):
            await self.cancel(run_id, attempt_id=attempt_id)
