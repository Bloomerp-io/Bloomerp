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
from collections.abc import AsyncIterable
from importlib.metadata import version
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
from pydantic import Field, JsonValue
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
from pydantic_ai.result import AgentStream
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets.external import ExternalToolset
from pydantic_ai.usage import RunUsage as ProviderUsage
from pydantic_ai.usage import UsageLimits

from bloomerp.agents.definition import AgentError
from bloomerp.agents.providers.builtins.pydantic_ai_common import (
    ModelFactory,
    PydanticAIProvider,
)
from bloomerp.agents.runtime import (
    AgentRuntimeAttempt,
    AgentRuntimeBudgetExceeded,
    AgentRuntimeCheckpoint,
    AgentRuntimeCredentials,
    AgentRuntimeMessage,
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


class _State(AgentRuntimeState):
    """Preserve SDK continuation fields alongside the shared runtime state."""

    sdk_version: str = SDK_VERSION
    history: list[JsonValue] = Field(default_factory=list)
    queued_messages: list[JsonValue] = Field(default_factory=list)


def _provider(identifier: str) -> PydanticAIProvider:
    """Resolve integrations through the single shared provider registry."""
    from bloomerp.agents.providers.registry import AI_PROVIDER_REGISTRY

    definition = AI_PROVIDER_REGISTRY.get(identifier)
    if definition is None or definition.integration is None:
        raise ValueError(f"Unregistered PydanticAI provider: {identifier}")
    return definition.integration


def create_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Construct an SDK model using the registered provider's validated parameters."""
    registration = _provider(request.config.provider)
    registration.settings_schema.model_validate(request.config.parameters)
    return registration.factory(request, credentials, client)


def _model_tool_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Remove JSON text mirrors of structured MCP data without changing stored results."""
    if not isinstance(result, dict) or not isinstance(
        result.get("structuredContent"), dict
    ):
        return result
    blocks = result.get("content")
    if not isinstance(blocks, list):
        return result
    structured = json.dumps(
        result["structuredContent"], sort_keys=True, ensure_ascii=False
    )
    retained = []
    for block in blocks:
        # Annotated text and non-text blocks may carry additional information.
        if (
            isinstance(block, dict)
            and set(block) == {"type", "text"}
            and block["type"] == "text"
        ):
            try:
                decoded = json.loads(block["text"])
                if (
                    json.dumps(decoded, sort_keys=True, ensure_ascii=False)
                    == structured
                ):
                    continue
            except (TypeError, ValueError):
                pass
        retained.append(block)
    if len(retained) == len(blocks):
        return result
    projected = dict(result)
    if retained:
        projected["content"] = retained
    else:
        projected.pop("content")
    return projected


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
                        {
                            "is_error": block.is_error,
                            "result": _model_tool_result(block.result),
                        },
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
    """Adapt PydanticAI agents and histories to the shared runtime lifecycle."""

    runtime_name = "pydantic_ai"
    runtime_version = RUNTIME_VERSION

    def __init__(
        self,
        *,
        model_factory: ModelFactory | None = None,
    ) -> None:
        """Create fresh attempt state, optionally supplying an offline model factory for tests."""
        super().__init__()
        self._model_factory = model_factory

    def _validate_request(self, request: AgentRuntimeRunRequest) -> None:
        """Check registered model settings and supported artifact input modalities."""
        registration = _provider(request.config.provider)
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
            if item.validation_error is not None:
                content = {
                    "error": item.validation_error.model_dump(mode="json"),
                    "status": "failed",
                }
            else:
                assert outcome is not None
                content = (
                    _model_tool_result(outcome.result)
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
        registration = _provider(request.config.provider)
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
