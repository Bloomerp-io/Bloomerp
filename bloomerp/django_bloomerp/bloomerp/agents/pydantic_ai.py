"""PydanticAI adapter with durable, coordinator-controlled tool execution.

OpenAI uses Responses; Anthropic uses Messages; DeepSeek and ``openai_chat`` use
Chat Completions. Credentials and HTTP clients are scoped to an attempt. This
module does not depend on Django, Redis, or a worker: a runner may consume it in
an async request or a worker (or via an async bridge from synchronous code).

Only extracted artifact content is supported initially. Native file uploads and
cost accounting require separate integrations; unsupported budgets/settings are
rejected rather than silently ignored. Checkpoints contain sensitive model
history and must have the same access restrictions as the conversation.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, Callable, Mapping
from dataclasses import dataclass
from importlib.metadata import version
from types import MappingProxyType
from typing import Any, Literal, Self, cast
from uuid import UUID, uuid4

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import Field, JsonValue, model_validator
from pydantic_ai import Agent, DeferredToolRequests, RunContext
from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import (
    AgentStreamEvent,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    SystemPromptPart,
    TextPart,
    TextPartDelta,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.result import AgentStream
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets.external import ExternalToolset
from pydantic_ai.usage import RunUsage as ProviderUsage
from pydantic_ai.usage import UsageLimits

from bloomerp.agents.definition import AgentError
from bloomerp.agents.runtime import (
    AgentRuntimeAttempt,
    AgentRuntimeBudgetExceeded,
    AgentRuntimeCheckpoint,
    AgentRuntimeCredentials,
    AgentRuntimeMessage,
    AgentRuntimePayload,
    AgentRuntimePendingToolProposal,
    AgentRuntimeRunFinishedEvent,
    AgentRuntimeRunPausedEvent,
    AgentRuntimeRunRequest,
    AgentRuntimeState,
    AgentRuntimeTextDeltaEvent,
    AgentRuntimeToolCoordinator,
    AgentRuntimeToolProposal,
    BaseAgentRuntime,
)

SDK_VERSION = version("pydantic-ai-slim")
RUNTIME_VERSION = "1"


class PydanticAISettings(AgentRuntimePayload):
    """Allow documented model controls without bypassing the tool/secret boundary.

    ``max_tokens`` is a per-response output cap, separate from the run's token
    budget. Provider-specific settings can be added deliberately as needed.
    Arbitrary headers, request bodies, and provider-hosted tools are not accepted.
    """

    max_tokens: int | None = Field(default=None, gt=0, strict=True)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    parallel_tool_calls: bool | None = Field(default=None, strict=True)
    seed: int | None = Field(default=None, strict=True)
    stop_sequences: list[str] | None = None
    openai_reasoning_effort: (
        Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None
    ) = None


class _State(AgentRuntimeState):
    """Preserve SDK continuation fields alongside the shared runtime state."""

    sdk_version: str = SDK_VERSION
    history: list[JsonValue] = Field(default_factory=list)
    queued_messages: list[JsonValue] = Field(default_factory=list)


type ModelFactory = Callable[
    [AgentRuntimeRunRequest, AgentRuntimeCredentials, httpx.AsyncClient], Model
]


class AnthropicSettings(PydanticAISettings):
    """Validate the settings supported by the built-in Anthropic integration."""

    @model_validator(mode="after")
    def validate_supported_settings(self) -> Self:
        """Reject OpenAI-only controls before an Anthropic model is contacted."""
        if self.openai_reasoning_effort is not None:
            raise ValueError("openai_reasoning_effort is not an Anthropic setting")
        if self.seed is not None:
            raise ValueError("Anthropic does not support seed")
        return self


@dataclass(frozen=True)
class PydanticAIProvider:
    """Register a model factory and its typed settings for one provider identifier.

    Factories receive the request, explicit credentials, and an attempt-owned HTTP
    client. They must return a PydanticAI Model, avoid global credential defaults,
    and use the supplied client or manage their own resources. Settings subclasses
    can add validated provider-specific options without modifying the runtime.
    """

    factory: ModelFactory
    settings_schema: type[PydanticAISettings] = PydanticAISettings


def _api_key(credentials: AgentRuntimeCredentials) -> str:
    """Require explicit API credentials for the built-in remote providers."""
    if credentials.api_key is None or not credentials.api_key.get_secret_value():
        raise ValueError("This provider requires explicitly resolved API credentials")
    return credentials.api_key.get_secret_value()


def _openai_client(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
    *,
    default_url: str = "https://api.openai.com/v1",
) -> AsyncOpenAI:
    """Build a compatible SDK client without ambient API keys or endpoint defaults."""
    return AsyncOpenAI(
        api_key=_api_key(credentials),
        base_url=request.config.base_url or default_url,
        http_client=client,
        max_retries=0,
    )


def create_openai_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Construct an OpenAI Responses model using the instance configuration."""
    provider = OpenAIProvider(
        openai_client=_openai_client(request, credentials, client)
    )
    return OpenAIResponsesModel(request.config.model, provider=provider)


def create_openai_chat_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Construct a Chat Completions model, including configured compatible endpoints."""
    provider = OpenAIProvider(
        openai_client=_openai_client(request, credentials, client)
    )
    return OpenAIChatModel(request.config.model, provider=provider)


def create_deepseek_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Construct a DeepSeek model with its provider-specific reasoning profile."""
    sdk = _openai_client(
        request, credentials, client, default_url="https://api.deepseek.com"
    )
    return OpenAIChatModel(
        request.config.model, provider=DeepSeekProvider(openai_client=sdk)
    )


def create_anthropic_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Construct an Anthropic Messages model using explicit instance credentials."""
    sdk = AsyncAnthropic(
        api_key=_api_key(credentials),
        base_url=request.config.base_url or "https://api.anthropic.com",
        http_client=client,
        max_retries=0,
    )
    return AnthropicModel(
        request.config.model, provider=AnthropicProvider(anthropic_client=sdk)
    )


def default_providers() -> dict[str, PydanticAIProvider]:
    """Return fresh registrations so customization never changes another runtime."""
    return {
        "openai": PydanticAIProvider(create_openai_model),
        "openai_chat": PydanticAIProvider(create_openai_chat_model),
        "anthropic": PydanticAIProvider(create_anthropic_model, AnthropicSettings),
        "deepseek": PydanticAIProvider(create_deepseek_model),
    }


def _provider(
    identifier: str,
    providers: Mapping[str, PydanticAIProvider],
) -> PydanticAIProvider:
    """Resolve a registered provider without silently falling back to another API."""
    try:
        return providers[identifier]
    except KeyError:
        raise ValueError(f"Unregistered PydanticAI provider: {identifier}") from None


def create_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
    *,
    providers: Mapping[str, PydanticAIProvider] | None = None,
) -> Model:
    """Construct a model through the supplied registry or built-in registrations."""
    registration = _provider(
        request.config.provider, default_providers() if providers is None else providers
    )
    registration.settings_schema.model_validate(request.config.parameters)
    return registration.factory(request, credentials, client)


def _messages(
    messages: tuple[AgentRuntimeMessage, ...], history: list[ModelMessage]
) -> list[ModelMessage]:
    """Translate portable input while retaining provider call/result pairing."""
    names = {
        part.tool_call_id: part.tool_name
        for message in history
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    }
    converted: list[ModelMessage] = []
    for message in messages:
        parts: list[Any] = []
        for block in message.content:
            if block.type == "tool_call":
                names[block.provider_call_id] = block.tool_identifier
                parts.append(
                    ToolCallPart(
                        block.tool_identifier, block.arguments, block.provider_call_id
                    )
                )
            elif block.type == "tool_result":
                if block.provider_call_id not in names:
                    raise ValueError("Tool result has no matching tool call in context")
                parts.append(
                    ToolReturnPart(
                        names[block.provider_call_id],
                        {"is_error": block.is_error, "result": block.result},
                        block.provider_call_id,
                    )
                )
            else:
                text = (
                    block.text
                    if block.type == "text"
                    else json.dumps(
                        {
                            "artifact_id": str(block.artifact_id),
                            "media_type": block.media_type,
                            "content": block.content,
                        },
                        ensure_ascii=False,
                    )
                )
                if message.role == "assistant":
                    parts.append(TextPart(text))
                elif message.role == "system":
                    parts.append(SystemPromptPart(text))
                else:
                    parts.append(UserPromptPart(text))
        if parts:
            converted.append(
                ModelResponse(parts)
                if message.role == "assistant"
                else ModelRequest(parts)
            )
    return converted


def _serialize(history: list[ModelMessage]) -> list[JsonValue]:
    """Round-trip all SDK message parts, including opaque reasoning continuation."""
    return json.loads(ModelMessagesTypeAdapter.dump_json(history))


class PydanticAIRuntime(BaseAgentRuntime[_State]):
    """Adapt PydanticAI models and histories to the shared runtime lifecycle."""

    runtime_name = "pydantic_ai"
    runtime_version = RUNTIME_VERSION

    def __init__(
        self,
        *,
        providers: Mapping[str, PydanticAIProvider] | None = None,
        model_factory: ModelFactory | None = None,
    ) -> None:
        """Copy instance provider registrations and optionally override models for tests.

        Supplied registrations extend or override the defaults for this runtime
        only. Model names remain unrestricted strings selected per request.
        """
        super().__init__()
        registrations = default_providers()
        if providers is not None:
            registrations.update(providers)
        self._providers = MappingProxyType(registrations)
        self._model_factory = model_factory

    def _validate_request(self, request: AgentRuntimeRunRequest) -> None:
        """Check registered model settings and supported artifact input modalities."""
        registration = _provider(request.config.provider, self._providers)
        registration.settings_schema.model_validate(request.config.parameters)
        for message in request.messages:
            for block in message.content:
                if block.type == "artifact" and (
                    message.role != "user" or not block.content
                ):
                    raise ValueError(
                        "Artifacts require extracted content in a user message; native file URLs are not supported"
                    )

    def _initial_state(self, request: AgentRuntimeRunRequest) -> _State:
        """Convert portable initial messages into PydanticAI history."""
        return _State(history=_serialize(_messages(request.messages, [])))

    def _restore_state(self, checkpoint: AgentRuntimeCheckpoint) -> _State:
        """Restore supported SDK history without discarding opaque continuation parts."""
        state = _State.model_validate(checkpoint.state)
        if state.sdk_version != SDK_VERSION:
            raise ValueError(
                "Checkpoint SDK version requires an explicit history migration"
            )
        ModelMessagesTypeAdapter.validate_python(state.history)
        ModelMessagesTypeAdapter.validate_python(state.queued_messages)
        return state

    def _add_messages(self, request: AgentRuntimeRunRequest, state: _State) -> None:
        """Queue steering after outstanding tool results in the restored transcript."""
        history = ModelMessagesTypeAdapter.validate_python(state.history)
        new_messages = _messages(request.messages, history)
        state.queued_messages.extend(_serialize(new_messages))
        if new_messages:
            state.finished = False

    def _classify_error(self, error: Exception) -> AgentError:
        """Map SDK failures to safe portable errors, delegating common classifications."""
        if isinstance(error, UsageLimitExceeded):
            return super()._classify_error(AgentRuntimeBudgetExceeded())
        if isinstance(error, httpx.TimeoutException):
            return super()._classify_error(TimeoutError())
        if isinstance(error, ModelHTTPError):
            return AgentError(
                code="provider_error",
                message="The model provider rejected the request.",
                retryable=error.status_code == 429 or error.status_code >= 500,
                details={"exception_type": type(error).__name__},
            )
        return super()._classify_error(error)

    def _apply_tool_results(self, state: _State) -> None:
        """Convert reconciled outcomes to PydanticAI tool-return message parts."""
        history = ModelMessagesTypeAdapter.validate_python(state.history)
        results = []
        for item in state.pending:
            outcome = item.outcome
            assert outcome is not None
            content = (
                outcome.result
                if outcome.status == "completed"
                else {
                    "error": outcome.error.model_dump(mode="json")
                    if outcome.error
                    else {},
                    "status": outcome.status,
                }
            )
            results.append(
                ToolReturnPart(
                    item.proposal.tool_identifier,
                    content,
                    item.proposal.provider_call_id,
                )
            )
        if results:
            history.append(ModelRequest(results))
        state.history = _serialize(history)

    async def _run(
        self,
        attempt: AgentRuntimeAttempt,
        state: _State,
        credentials: AgentRuntimeCredentials,
        coordinator: AgentRuntimeToolCoordinator,
    ) -> AgentRuntimeRunFinishedEvent | AgentRuntimeRunPausedEvent:
        """Alternate SDK model turns and durable external-tool reconciliation."""
        tokens = ProviderUsage()
        request = attempt.request
        identity = {"run_id": request.run_id, "attempt_id": request.attempt_id}
        registration = _provider(request.config.provider, self._providers)
        settings = registration.settings_schema.model_validate(
            request.config.parameters
        ).model_dump(exclude_none=True)
        settings["timeout"] = request.config.request_timeout_seconds
        async with httpx.AsyncClient(
            timeout=request.config.request_timeout_seconds
        ) as client:
            factory = self._model_factory or registration.factory
            model = factory(request, credentials, client)
            agent = Agent(
                model,
                output_type=[str, DeferredToolRequests],
                instructions=request.config.instructions,
                retries=0,
                instrument=False,
                toolsets=[
                    ExternalToolset(
                        [
                            ToolDefinition(
                                name=tool.identifier,
                                description=tool.description,
                                parameters_json_schema=cast(
                                    dict[str, Any], tool.input_schema
                                ),
                            )
                            for tool in request.tools
                        ]
                    )
                ],
            )
            await self._save(attempt, state)
            while not state.finished:
                if state.pending:
                    paused = await self._dispatch(attempt, state, coordinator)
                    if paused is not None:
                        return paused
                state.history.extend(state.queued_messages)
                state.queued_messages = []
                history = ModelMessagesTypeAdapter.validate_python(state.history)
                limit = request.budgets.max_tokens
                remaining = (
                    None
                    if limit is None
                    else limit
                    - request.usage.input_tokens
                    - request.usage.output_tokens
                )
                if remaining is not None and tokens.total_tokens >= remaining:
                    raise UsageLimitExceeded("Token budget exhausted")
                turn_settings = dict(settings)
                if remaining is not None:
                    output_cap = remaining - tokens.total_tokens
                    turn_settings["max_tokens"] = min(
                        settings.get("max_tokens", output_cap), output_cap
                    )
                message_id = uuid4()
                visible_part_indexes: dict[int, int] = {}

                async def on_event(
                    context: RunContext[None],
                    events: AsyncIterable[AgentStreamEvent],
                    output_message_id: UUID = message_id,
                    output_part_indexes: dict[int, int] = visible_part_indexes,
                ) -> None:
                    """Map visible text to contiguous blocks while retaining reasoning privately."""
                    try:
                        async for event in events:
                            text = None
                            if isinstance(event, PartStartEvent) and isinstance(
                                event.part, TextPart
                            ):
                                text = event.part.content
                            elif isinstance(event, PartDeltaEvent) and isinstance(
                                event.delta, TextPartDelta
                            ):
                                text = event.delta.content_delta
                            if text:
                                block_index = output_part_indexes.setdefault(
                                    event.index, len(output_part_indexes)
                                )
                                await attempt.emit(
                                    AgentRuntimeTextDeltaEvent(
                                        **identity,
                                        message_id=output_message_id,
                                        block_index=block_index,
                                        format="markdown",
                                        text=text,
                                    )
                                )
                    finally:
                        if isinstance(events, AgentStream):
                            # SDK aggregate usage updates only after a successful
                            # response. Retain observed usage on interruption too.
                            observed = events.usage()
                            attempt.record_tokens(
                                input_tokens=observed.input_tokens,
                                output_tokens=observed.output_tokens,
                            )

                # The SDK run owns its streams/tasks. Cancelling our producer
                # unwinds it without leaving a detached model or tool operation.
                result = await agent.run(
                    message_history=history,
                    model_settings=cast(ModelSettings, turn_settings),
                    usage=tokens,
                    usage_limits=UsageLimits(
                        total_tokens_limit=remaining, request_limit=50
                    ),
                    event_stream_handler=on_event,
                )
                attempt.record_tokens(
                    input_tokens=tokens.input_tokens, output_tokens=tokens.output_tokens
                )
                state.history = _serialize(result.all_messages())
                if isinstance(result.output, DeferredToolRequests):
                    catalog = {tool.identifier: tool for tool in request.tools}
                    seen: set[str] = set()
                    for call in result.output.calls:
                        if call.tool_call_id in seen:
                            raise ValueError(
                                "Provider returned duplicate tool call identities"
                            )
                        seen.add(call.tool_call_id)
                        tool = catalog[call.tool_name]
                        state.pending.append(
                            AgentRuntimePendingToolProposal(
                                proposal=AgentRuntimeToolProposal(
                                    provider_call_id=call.tool_call_id,
                                    tool_identifier=call.tool_name,
                                    tool_version=tool.version,
                                    arguments=call.args_as_dict(),
                                )
                            )
                        )
                    if not state.pending or result.output.approvals:
                        raise ValueError(
                            "Unexpected SDK approval request outside the coordinator"
                        )
                else:
                    state.finished = True
                # Commit full provider history and all proposed calls before tools.
                await self._save(attempt, state)
        return AgentRuntimeRunFinishedEvent(
            **identity, kind="run.completed", usage=attempt.usage()
        )
