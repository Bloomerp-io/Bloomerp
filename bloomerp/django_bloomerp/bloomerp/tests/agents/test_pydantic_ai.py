"""Exercise the real PydanticAI loop with local models and a fake coordinator."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from pydantic import JsonValue
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ThinkingPart,
    ToolReturnPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaThinkingPart,
    DeltaToolCall,
    FunctionModel,
)

from bloomerp.agents.runtime import (
    AgentRuntimeCheckpoint,
    AgentRuntimeConfig,
    AgentRuntimeCredentials,
    AgentRuntimeEvent,
    AgentRuntimeMessage,
    AgentRuntimeResumeRequest,
    AgentRuntimeRunRequest,
    AgentRuntimeToolOutcome,
    AgentRuntimeToolProposal,
)
from bloomerp.agents.runtimes.pydantic_ai import PydanticAIRuntime


class Coordinator:
    """Record calls and allow an external approval decision between attempts."""

    def __init__(self, *, waiting: bool = False) -> None:
        """Initialize deterministic stored outcomes and dispatch records."""
        self.waiting = waiting
        self.calls: list[AgentRuntimeToolProposal] = []
        self.resolved: list[UUID] = []
        self.call_id = uuid4()
        self.approval_id = uuid4()

    async def call(self, proposal: AgentRuntimeToolProposal) -> AgentRuntimeToolOutcome:
        """Emulate one durable proposal with either a result or approval wait."""
        self.calls.append(proposal)
        return self.outcome()

    def outcome(self) -> AgentRuntimeToolOutcome:
        """Produce the current durable state of the example call."""
        return AgentRuntimeToolOutcome(
            tool_call_id=self.call_id,
            provider_call_id="call-1",
            status="waiting" if self.waiting else "completed",
            approval_ids=(self.approval_id,) if self.waiting else (),
            result=None if self.waiting else {"value": 42},
        )

    async def resolve(self, tool_call_id: UUID) -> AgentRuntimeToolOutcome:
        """Reconcile the stored call without repeating its execution."""
        self.resolved.append(tool_call_id)
        return self.outcome()


class PydanticAIRuntimeTests(IsolatedAsyncioTestCase):
    """Verify orchestration boundaries without network, Django, or API keys."""

    def setUp(self) -> None:
        """Prepare instance configuration and a schema-described external tool."""
        self.request = AgentRuntimeRunRequest(
            run_id=uuid4(),
            attempt_id=uuid4(),
            config=AgentRuntimeConfig(
                runtime="pydantic_ai",
                provider="openai",
                model="test-model",
                agent_key="bloomai",
                agent_version="1",
            ),
            context={
                "user_id": "1",
                "conversation_id": uuid4(),
            },
            messages=(
                AgentRuntimeMessage(
                    role="user",
                    message_id=uuid4(),
                    sequence=1,
                    content=({"type": "text", "text": "Look it up"},),
                ),
            ),
            tools=(
                {
                    "identifier": "lookup",
                    "version": "1",
                    "description": "Look up a value",
                    "input_schema": {
                        "type": "object",
                        "properties": {"key": {"type": "string"}},
                        "required": ["key"],
                        "additionalProperties": False,
                    },
                },
            ),
        )
        self.histories: list[list[ModelMessage]] = []
        self.clients: list[httpx.AsyncClient] = []
        self.runtime = PydanticAIRuntime(model_factory=self.factory)
        self.coordinator = Coordinator()

    async def asyncTearDown(self) -> None:
        """Release adapters even after assertion failures."""
        await self.runtime.aclose()

    async def test_model_receives_structured_result_without_duplicate_text(
        self,
    ) -> None:
        """Project MCP results for the model while retaining the complete coordinator outcome."""
        outcome = self.coordinator.outcome().model_copy(
            update={
                "result": {
                    "structuredContent": {"value": 42},
                    "content": [{"type": "text", "text": '{"value":42}'}],
                }
            }
        )
        with patch.object(self.coordinator, "outcome", return_value=outcome):
            events = await self.collect(self.request)
        self.assertEqual(events[-1].kind, "run.completed")
        returns = [
            part
            for message in self.histories[-1]
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        self.assertEqual(returns[-1].content, {"structuredContent": {"value": 42}})
        self.assertEqual(
            outcome.result["content"], [{"type": "text", "text": '{"value":42}'}]
        )

    def factory(
        self,
        request: AgentRuntimeRunRequest,
        credentials: AgentRuntimeCredentials,
        client: httpx.AsyncClient,
    ) -> Model:
        """Inject a real SDK FunctionModel and retain its owned client for checks."""
        self.clients.append(client)
        return FunctionModel(stream_function=self.model_stream)

    async def model_stream(
        self,
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        """Ask for a tool, then stream visible text after receiving its result."""
        self.histories.append(list(messages))
        returned = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        )
        if not returned:
            yield {
                0: DeltaToolCall(
                    name="lookup", json_args='{"key":"answer"}', tool_call_id="call-1"
                )
            }
        else:
            yield "The answer "
            yield "is 42."

    async def collect(
        self, request: AgentRuntimeRunRequest | AgentRuntimeResumeRequest
    ) -> list[AgentRuntimeEvent]:
        """Consume all events while the adapter waits for each caller acknowledgment."""
        method = (
            self.runtime.resume
            if isinstance(request, AgentRuntimeResumeRequest)
            else self.runtime.execute
        )
        return [
            event
            async for event in method(
                request,
                credentials=AgentRuntimeCredentials(api_key="never-serialize-me"),
                coordinator=self.coordinator,
            )
        ]

    def resumed(
        self, checkpoint: AgentRuntimeCheckpoint, **changes: object
    ) -> AgentRuntimeResumeRequest:
        """Prepare a fresh attempt with no repeated transcript input."""
        run = self.request.model_copy(
            update={"attempt_id": uuid4(), "messages": (), **changes}
        )
        return AgentRuntimeResumeRequest(run=run, checkpoint=checkpoint)

    async def test_streaming_calls_coordinator_and_preserves_history(self) -> None:
        """Run two model rounds, stream text, and close the attempt's client."""
        events = await self.collect(self.request)
        self.assertEqual(events[-1].kind, "run.completed", events[-1])
        self.assertEqual(
            "".join(e.text for e in events if e.kind == "text.delta"),
            "The answer is 42.",
        )
        self.assertEqual(len(self.coordinator.calls), 1)
        self.assertEqual(events[-1].usage.tool_calls, 1)
        self.assertGreater(events[-1].usage.input_tokens, 0)
        self.assertEqual(len(self.histories), 2)
        self.assertTrue(all(client.is_closed for client in self.clients))
        self.assertNotIn(
            "never-serialize-me", "".join(event.model_dump_json() for event in events)
        )

    async def test_pause_and_resume_resolve_without_repeating_effects(self) -> None:
        """Retain pending provider history across approval pauses and a fresh attempt."""
        self.coordinator.waiting = True
        events = await self.collect(self.request)
        self.assertEqual(events[-1].kind, "run.paused", events[-1])
        checkpoint = AgentRuntimeCheckpoint.model_validate_json(
            events[-1].checkpoint.model_dump_json()
        )
        still_waiting = await self.collect(
            self.resumed(checkpoint, usage=events[-1].usage)
        )
        self.assertEqual(still_waiting[-1].kind, "run.paused")
        self.assertEqual(len(self.histories), 1)
        self.coordinator.waiting = False
        resumed = await self.collect(
            self.resumed(still_waiting[-1].checkpoint, usage=events[-1].usage)
        )
        self.assertEqual(resumed[-1].kind, "run.completed", resumed[-1])
        self.assertEqual(len(self.coordinator.calls), 1)
        self.assertEqual(self.coordinator.resolved, [self.coordinator.call_id] * 2)
        self.assertEqual(resumed[-1].usage.tool_calls, 0)

    async def test_new_input_waits_until_pending_tool_result(self) -> None:
        """Place steering after matching results rather than splitting a tool exchange."""
        self.coordinator.waiting = True
        first = await self.collect(self.request)
        new = AgentRuntimeMessage(
            role="user",
            sequence=2,
            message_id=uuid4(),
            content=({"type": "text", "text": "Please be brief"},),
        )
        paused = await self.collect(self.resumed(first[-1].checkpoint, messages=(new,)))
        self.assertEqual(paused[-1].checkpoint.consumed_message_sequence, 2)
        self.coordinator.waiting = False
        await self.collect(self.resumed(paused[-1].checkpoint))
        parts = [part for message in self.histories[-1] for part in message.parts]
        tool_position = next(
            i for i, part in enumerate(parts) if isinstance(part, ToolReturnPart)
        )
        steering_position = next(
            i
            for i, part in enumerate(parts)
            if getattr(part, "content", None) == "Please be brief"
        )
        self.assertLess(tool_position, steering_position)

    async def test_checkpoint_backpressure_precedes_tool_dispatch(self) -> None:
        """Do not execute proposed actions before the caller commits their checkpoint."""
        stream = self.runtime.execute(
            self.request,
            credentials=AgentRuntimeCredentials(),
            coordinator=self.coordinator,
        )
        try:
            async for event in stream:
                if (
                    event.kind == "checkpoint.created"
                    and event.checkpoint.state["pending"]
                ):
                    await asyncio.sleep(0)
                    self.assertEqual(self.coordinator.calls, [])
                    break
        finally:
            await stream.aclose()
        self.assertTrue(all(client.is_closed for client in self.clients))

    async def test_completed_checkpoint_does_not_generate_again(self) -> None:
        """Recover a committed final model response without a duplicate provider request."""
        events = await self.collect(self.request)
        checkpoint = [e.checkpoint for e in events if e.kind == "checkpoint.created"][
            -1
        ]
        restored = await self.collect(self.resumed(checkpoint))
        self.assertEqual(restored[-1].kind, "run.completed")
        self.assertEqual(len(self.histories), 2)
        self.assertEqual(restored[-1].usage.input_tokens, 0)

    async def test_missing_tool_on_resume_never_executes(self) -> None:
        """Require the refreshed tool catalog before resolving a pending effect."""
        self.coordinator.waiting = True
        first = await self.collect(self.request)
        self.coordinator.waiting = False
        events = await self.collect(self.resumed(first[-1].checkpoint, tools=()))
        self.assertEqual(events[-1].kind, "run.failed")
        self.assertEqual(self.coordinator.resolved, [])

    async def test_token_budget_accounts_for_previous_attempts(self) -> None:
        """Reject exhausted lifetime usage before opening a provider stream."""
        request = AgentRuntimeRunRequest.model_validate(
            self.request.model_dump()
            | {
                "budgets": {"max_tokens": 10},
                "usage": {"input_tokens": 10},
            }
        )
        events = await self.collect(request)
        self.assertEqual(events[-1].kind, "run.failed")
        self.assertEqual(events[-1].error.code, "budget_exceeded")
        self.assertEqual(self.histories, [])

    async def test_tool_budget_accounts_for_previous_attempts(self) -> None:
        """Refuse an additional effect when earlier attempts exhausted the tool budget."""
        request = AgentRuntimeRunRequest.model_validate(
            self.request.model_dump()
            | {
                "budgets": {"max_tool_calls": 1},
                "usage": {"tool_calls": 1},
            }
        )
        events = await self.collect(request)
        self.assertEqual(events[-1].error.code, "budget_exceeded")
        self.assertEqual(self.coordinator.calls, [])

    async def test_unsupported_options_and_cost_budget_fail_before_execution(
        self,
    ) -> None:
        """Reject options that would bypass tool control or require unimplemented accounting."""
        for parameters in (
            {"extra_headers": {"Authorization": "secret"}},
            {"max_tokens": -1},
        ):
            config = self.request.config.model_copy(update={"parameters": parameters})
            with self.assertRaises(ValueError):
                self.runtime.execute(
                    self.request.model_copy(update={"config": config}),
                    credentials=AgentRuntimeCredentials(),
                    coordinator=self.coordinator,
                )
        with self.assertRaises(ValueError):
            AgentRuntimeRunRequest.model_validate(
                self.request.model_dump() | {"budgets": {"max_cost": 1}}
            )

    async def test_cancel_interrupts_model_and_closes_client(self) -> None:
        """Cancel the exact attempt while its provider is awaiting a response."""
        entered = asyncio.Event()
        exited = asyncio.Event()

        async def blocked_model(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str]:
            """Keep the model suspended until cancellation unwinds its generator."""
            entered.set()
            try:
                await asyncio.Event().wait()
                yield "unreachable"
            finally:
                exited.set()

        self.model_stream = blocked_model
        consumer = asyncio.create_task(self.collect(self.request))
        await asyncio.wait_for(entered.wait(), timeout=3)
        await self.runtime.cancel(self.request.run_id, attempt_id=uuid4())
        self.assertFalse(consumer.done())
        await self.runtime.cancel(
            self.request.run_id, attempt_id=self.request.attempt_id
        )
        events = await asyncio.wait_for(consumer, timeout=3)
        self.assertEqual(events[-1].kind, "run.cancelled")
        self.assertTrue(exited.is_set())
        self.assertTrue(all(client.is_closed for client in self.clients))

    async def test_sdk_version_mismatch_is_rejected(self) -> None:
        """Fail explicitly rather than silently dropping unknown continuation fields."""
        events = await self.collect(self.request)
        checkpoint = [
            event.checkpoint for event in events if event.kind == "checkpoint.created"
        ][-1]
        checkpoint.state["sdk_version"] = "unknown"
        with self.assertRaisesRegex(ValueError, "migration"):
            self.runtime.resume(
                self.resumed(checkpoint),
                credentials=AgentRuntimeCredentials(),
                coordinator=self.coordinator,
            )

    async def test_invalid_tool_arguments_recover_without_execution(self) -> None:
        """Return safe validation details, then execute only the corrected model call."""
        cases = (
            (
                {"tab_id": ""},
                {},
                {"type": "object", "properties": {}, "additionalProperties": False},
                "additionalProperties",
            ),
            (
                {"refresh": "false"},
                {},
                {"type": "object", "properties": {}, "additionalProperties": False},
                "additionalProperties",
            ),
            (
                {"key": {"private": "never-echo-this-value"}},
                {"key": "answer"},
                self.request.tools[0].input_schema,
                "type",
            ),
            ({}, {"key": "answer"}, self.request.tools[0].input_schema, "required"),
        )
        for invalid, valid, schema, validator in cases:
            with self.subTest(arguments=invalid):
                self.coordinator.calls.clear()
                request = self.request.model_copy(
                    update={
                        "attempt_id": uuid4(),
                        "tools": (
                            self.request.tools[0].model_copy(
                                update={"input_schema": schema}
                            ),
                        ),
                    }
                )

                async def correcting_model(
                    messages: list[ModelMessage],
                    info: AgentInfo,
                    invalid: dict[str, JsonValue] = invalid,
                    valid: dict[str, JsonValue] = valid,
                    validator: str = validator,
                ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
                    """Correct the invalid proposal after inspecting its tool-level failure."""
                    returns = [
                        part
                        for message in messages
                        for part in message.parts
                        if isinstance(part, ToolReturnPart)
                    ]
                    if not returns:
                        yield {
                            0: DeltaToolCall(
                                name="lookup",
                                json_args=json.dumps(invalid),
                                tool_call_id="invalid-call",
                            )
                        }
                    elif len(returns) == 1:
                        error = returns[0].content["error"]
                        self.assertEqual(returns[0].tool_call_id, "invalid-call")
                        self.assertEqual(error["code"], "tool_validation_error")
                        self.assertTrue(error["retryable"])
                        self.assertEqual(error["details"]["validator"], validator)
                        self.assertNotIn("never-echo-this-value", json.dumps(error))
                        self.assertEqual(self.coordinator.calls, [])
                        yield {
                            0: DeltaToolCall(
                                name="lookup",
                                json_args=json.dumps(valid),
                                tool_call_id="call-1",
                            )
                        }
                    else:
                        yield "Corrected and completed."

                self.model_stream = correcting_model
                events = await self.collect(request)
                self.assertEqual(events[-1].kind, "run.completed", events[-1])
                self.assertEqual(
                    [call.arguments for call in self.coordinator.calls], [valid]
                )
                self.assertEqual(events[-1].usage.tool_calls, 2)
                self.assertEqual(
                    len([event for event in events if event.kind == "tool.outcome"]), 1
                )

    async def test_invalid_calls_count_toward_tool_budget(self) -> None:
        """Bound repeated invalid proposals even when none reaches the coordinator."""

        async def invalid_model(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[dict[int, DeltaToolCall]]:
            """Keep proposing a new invalid call to exercise the shared attempt budget."""
            yield {
                0: DeltaToolCall(
                    name="lookup",
                    json_args='{"key":123}',
                    tool_call_id=f"invalid-{len(messages)}",
                )
            }

        self.model_stream = invalid_model
        request = AgentRuntimeRunRequest.model_validate(
            self.request.model_dump() | {"budgets": {"max_tool_calls": 2}}
        )
        events = await self.collect(request)
        self.assertEqual(events[-1].kind, "run.failed")
        self.assertEqual(events[-1].error.code, "budget_exceeded")
        self.assertEqual(events[-1].usage.tool_calls, 2)
        self.assertEqual(self.coordinator.calls, [])

    async def test_validation_checkpoint_resumes_without_execution(self) -> None:
        """Replay a checkpointed validation result without counting or dispatching it again."""

        async def recovering_model(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
            """Finish once the restored validation failure is returned to the model."""
            returns = [
                part
                for message in messages
                for part in message.parts
                if isinstance(part, ToolReturnPart)
            ]
            if returns:
                self.assertEqual(
                    returns[-1].content["error"]["code"], "tool_validation_error"
                )
                yield "Invalid arguments handled."
            else:
                yield {
                    0: DeltaToolCall(
                        name="lookup",
                        json_args='{"key":123}',
                        tool_call_id="invalid-call",
                    )
                }

        self.model_stream = recovering_model
        stream = self.runtime.execute(
            self.request,
            credentials=AgentRuntimeCredentials(),
            coordinator=self.coordinator,
        )
        checkpoint = None
        try:
            async for event in stream:
                if event.kind == "checkpoint.created" and any(
                    item.get("validation_error")
                    for item in event.checkpoint.state["pending"]
                ):
                    checkpoint = AgentRuntimeCheckpoint.model_validate_json(
                        event.checkpoint.model_dump_json()
                    )
                    break
        finally:
            await stream.aclose()
        self.assertIsNotNone(checkpoint)
        events = await self.collect(self.resumed(checkpoint))
        self.assertEqual(events[-1].kind, "run.completed", events[-1])
        self.assertEqual(events[-1].usage.tool_calls, 0)
        self.assertEqual(self.coordinator.calls, [])

    async def test_provider_failure_is_sanitized_and_closes_client(self) -> None:
        """Keep request bodies and credentials out of persisted failure events."""

        async def failing_model(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str]:
            """Emulate a provider exception containing sensitive diagnostic text."""
            raise RuntimeError("never-serialize-me and private request body")
            yield "unreachable"

        self.model_stream = failing_model
        events = await self.collect(self.request)
        self.assertEqual(events[-1].kind, "run.failed")
        self.assertNotIn("never-serialize-me", events[-1].model_dump_json())
        self.assertNotIn("private request body", events[-1].model_dump_json())
        self.assertTrue(all(client.is_closed for client in self.clients))

    async def test_duration_budget_unwinds_a_blocked_model(self) -> None:
        """Apply the remaining lifetime duration to a hanging provider request."""

        async def blocked_model(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str]:
            """Block indefinitely so only the adapter's deadline can finish the run."""
            await asyncio.Event().wait()
            yield "unreachable"

        self.model_stream = blocked_model
        request = AgentRuntimeRunRequest.model_validate(
            self.request.model_dump()
            | {
                "budgets": {"max_duration_seconds": 1},
                "usage": {"duration_seconds": 0.98},
            }
        )
        events = await asyncio.wait_for(self.collect(request), timeout=3)
        self.assertEqual(events[-1].kind, "run.failed")
        self.assertEqual(events[-1].error.code, "budget_exceeded")
        self.assertTrue(all(client.is_closed for client in self.clients))

    async def test_shutdown_wakes_consumer_and_rejects_new_runs(self) -> None:
        """Close a live stream without leaving its consumer waiting for an event."""
        stream = self.runtime.execute(
            self.request,
            credentials=AgentRuntimeCredentials(),
            coordinator=self.coordinator,
        )
        await anext(stream)
        await self.runtime.aclose()
        terminal = await asyncio.wait_for(anext(stream), timeout=3)
        self.assertEqual(terminal.kind, "run.cancelled")
        await stream.aclose()
        self.assertTrue(all(client.is_closed for client in self.clients))
        with self.assertRaisesRegex(ValueError, "closed"):
            self.runtime.execute(
                self.request,
                credentials=AgentRuntimeCredentials(),
                coordinator=self.coordinator,
            )

    async def test_recover_partial_batch_skips_completed_effect(self) -> None:
        """Resume between two effects without repeating the first completed action."""

        class BatchCoordinator:
            """Store outcomes by provider call identity for a two-call batch."""

            def __init__(self) -> None:
                """Initialize durable result records and invocation history."""
                self.calls: list[str] = []
                self.outcomes: dict[str, AgentRuntimeToolOutcome] = {}

            async def call(
                self, proposal: AgentRuntimeToolProposal
            ) -> AgentRuntimeToolOutcome:
                """Emulate durable idempotency keyed by provider call identity."""
                self.calls.append(proposal.provider_call_id)
                if proposal.provider_call_id not in self.outcomes:
                    self.outcomes[proposal.provider_call_id] = AgentRuntimeToolOutcome(
                        tool_call_id=uuid4(),
                        provider_call_id=proposal.provider_call_id,
                        status="completed",
                        result={"value": proposal.arguments["key"]},
                    )
                return self.outcomes[proposal.provider_call_id]

            async def resolve(self, tool_call_id: UUID) -> AgentRuntimeToolOutcome:
                """Locate a previously recorded result by its durable identifier."""
                return next(
                    outcome
                    for outcome in self.outcomes.values()
                    if outcome.tool_call_id == tool_call_id
                )

        async def batch_model(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
            """Request two independent tools, then reply after both results arrive."""
            self.histories.append(messages)
            if any(
                isinstance(part, ToolReturnPart)
                for message in messages
                for part in message.parts
            ):
                yield "Both complete"
            else:
                yield {
                    0: DeltaToolCall(
                        name="lookup", json_args='{"key":"a"}', tool_call_id="call-a"
                    ),
                    1: DeltaToolCall(
                        name="lookup", json_args='{"key":"b"}', tool_call_id="call-b"
                    ),
                }

        self.coordinator = BatchCoordinator()
        self.model_stream = batch_model
        stream = self.runtime.execute(
            self.request,
            credentials=AgentRuntimeCredentials(),
            coordinator=self.coordinator,
        )
        checkpoint = None
        async for event in stream:
            if event.kind == "checkpoint.created":
                pending = event.checkpoint.state["pending"]
                if pending and pending[0]["outcome"] is not None:
                    checkpoint = event.checkpoint
                    break
        await stream.aclose()
        self.assertIsNotNone(checkpoint)
        self.assertEqual(self.coordinator.calls, ["call-a"])
        events = await self.collect(self.resumed(checkpoint))
        self.assertEqual(events[-1].kind, "run.completed", events[-1])
        self.assertEqual(self.coordinator.calls, ["call-a", "call-b"])

    async def test_explicit_provider_construction(self) -> None:
        """Construct all supported SDK models with isolated credentials and endpoints."""
        from bloomerp.agents.runtimes.pydantic_ai import create_model

        async with httpx.AsyncClient() as client:
            for provider, expected_system in (
                ("openai", "openai"),
                ("openai_chat", "openai"),
                ("anthropic", "anthropic"),
                ("deepseek", "deepseek"),
            ):
                with self.subTest(provider=provider):
                    config = self.request.config.model_copy(
                        update={"provider": provider}
                    )
                    request = self.request.model_copy(update={"config": config})
                    model = create_model(
                        request, AgentRuntimeCredentials(api_key="instance-key"), client
                    )
                    self.assertEqual(model.system, expected_system)
                    self.assertEqual(model.model_name, "test-model")
                    self.assertEqual(model.client.api_key, "instance-key")
            with self.assertRaisesRegex(ValueError, "credentials"):
                create_model(self.request, AgentRuntimeCredentials(), client)

    async def test_opaque_reasoning_survives_approval_resume_without_streaming(
        self,
    ) -> None:
        """Preserve signed provider continuation while streaming only visible output."""

        async def reasoning_model(
            messages: list[ModelMessage],
            info: AgentInfo,
        ) -> AsyncIterator[
            str | dict[int, DeltaThinkingPart] | dict[int, DeltaToolCall]
        ]:
            """Include a signed thinking part before an approval-gated call."""
            self.histories.append(messages)
            if any(
                isinstance(part, ToolReturnPart)
                for message in messages
                for part in message.parts
            ):
                yield "Done"
            else:
                yield {
                    0: DeltaThinkingPart(
                        content="private thinking", signature="opaque-signature"
                    )
                }
                yield {
                    1: DeltaToolCall(
                        name="lookup",
                        json_args='{"key":"answer"}',
                        tool_call_id="call-1",
                    )
                }

        self.model_stream = reasoning_model
        self.coordinator.waiting = True
        events = await self.collect(self.request)
        self.assertEqual(events[-1].kind, "run.paused", events[-1])
        self.assertFalse(any(event.kind == "text.delta" for event in events))
        self.coordinator.waiting = False
        resumed = await self.collect(self.resumed(events[-1].checkpoint))
        self.assertEqual(resumed[-1].kind, "run.completed")
        reasoning = [
            part
            for message in self.histories[-1]
            for part in message.parts
            if isinstance(part, ThinkingPart)
        ]
        self.assertEqual(reasoning[0].signature, "opaque-signature")
        self.assertEqual(reasoning[0].content, "private thinking")
        self.assertEqual(
            "".join(event.text for event in resumed if event.kind == "text.delta"),
            "Done",
        )

    async def test_rejected_approval_is_returned_as_tool_error(self) -> None:
        """Let the model respond to a rejection without executing the action again."""
        self.coordinator.waiting = True
        events = await self.collect(self.request)

        async def reject(tool_call_id: UUID) -> AgentRuntimeToolOutcome:
            """Emulate the user's persisted rejection decision."""
            return AgentRuntimeToolOutcome(
                tool_call_id=tool_call_id,
                provider_call_id="call-1",
                status="rejected",
                error={
                    "code": "approval_rejected",
                    "message": "User declined the action",
                },
            )

        self.coordinator.resolve = reject
        resumed = await self.collect(self.resumed(events[-1].checkpoint))
        self.assertEqual(resumed[-1].kind, "run.completed")
        results = [
            part
            for message in self.histories[-1]
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        self.assertEqual(results[-1].content["status"], "rejected")
        self.assertEqual(len(self.coordinator.calls), 1)

    async def test_interrupted_response_retains_observed_token_usage(self) -> None:
        """Avoid resetting billed usage to zero when a partial model stream fails."""

        async def partial_model(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str]:
            """Emit one chunk with SDK usage before simulating a lost connection."""
            yield "Partial output"
            raise RuntimeError("Connection lost")

        self.model_stream = partial_model
        events = await self.collect(self.request)
        self.assertEqual(events[-1].kind, "run.failed")
        self.assertGreater(events[-1].usage.input_tokens, 0)
        self.assertGreater(events[-1].usage.output_tokens, 0)

    async def test_stream_token_limit_records_usage_that_exceeded_budget(self) -> None:
        """Persist observed usage even when the SDK aborts an over-budget response."""
        request = AgentRuntimeRunRequest.model_validate(
            self.request.model_dump() | {"budgets": {"max_tokens": 1}}
        )
        events = await self.collect(request)
        self.assertEqual(events[-1].kind, "run.failed")
        self.assertEqual(events[-1].error.code, "budget_exceeded")
        self.assertGreater(
            events[-1].usage.input_tokens + events[-1].usage.output_tokens, 1
        )
        self.assertEqual(self.coordinator.calls, [])

    def register_provider(self, key: str, integration: object) -> None:
        """Register an integration in the production registry with test-owned cleanup."""
        from bloomerp.agents.providers.definition import AIProviderDefinition
        from bloomerp.agents.providers.registry import (
            AI_PROVIDER_REGISTRY,
            pydantic_runtime,
        )

        AI_PROVIDER_REGISTRY.register(
            key,
            AIProviderDefinition(
                id=key,
                name=key,
                runtime_factory=pydantic_runtime,
                config_schema=integration.settings_schema,
                integration=integration,
            ),
        )
        self.addCleanup(self.remove_provider, key)

    def remove_provider(self, key: str) -> None:
        """Release a test-owned provider if the test has not already removed it."""
        from bloomerp.agents.providers.registry import AI_PROVIDER_REGISTRY

        if AI_PROVIDER_REGISTRY.get(key) is not None:
            AI_PROVIDER_REGISTRY.unregister(key)

    async def test_registered_provider_executes_with_custom_validated_settings(
        self,
    ) -> None:
        """Support a new provider and typed options without changing runtime dispatch."""
        from pydantic import Field

        from bloomerp.agents.providers.builtins.pydantic_ai_common import (
            PydanticAISettings,
        )
        from bloomerp.agents.runtime import AgentRuntime
        from bloomerp.agents.runtimes.pydantic_ai import PydanticAIProvider

        class VendorSettings(PydanticAISettings):
            """Describe an additional control understood by this example provider."""

            vendor_top_k: int = Field(gt=0, strict=True)

        async def vendor_model(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str]:
            """Verify custom settings reach the model and return ordinary text."""
            self.assertEqual(info.model_settings["vendor_top_k"], 7)
            yield "Custom provider works"

        self.model_stream = vendor_model
        self.register_provider(
            "vendor", PydanticAIProvider(self.factory, VendorSettings)
        )
        self.runtime = PydanticAIRuntime()
        self.assertIn(AgentRuntime, PydanticAIRuntime.__mro__)
        config = self.request.config.model_copy(
            update={
                "provider": "vendor",
                "model": "any-instance-selected-model",
                "parameters": {"vendor_top_k": 7},
            }
        )
        request = self.request.model_copy(update={"config": config})
        events = await self.collect(request)
        self.assertEqual(events[-1].kind, "run.completed", events[-1])
        self.assertEqual(
            "".join(event.text for event in events if event.kind == "text.delta"),
            "Custom provider works",
        )
        invalid = config.model_copy(update={"parameters": {"vendor_top_k": 0}})
        with self.assertRaises(ValueError):
            self.runtime.validate_request(
                request.model_copy(update={"config": invalid})
            )

    async def test_provider_registry_is_shared(self) -> None:
        """Ensure fresh runtimes resolve custom integrations through one shared registry."""
        from bloomerp.agents.runtimes.pydantic_ai import PydanticAIProvider

        self.register_provider("vendor", PydanticAIProvider(self.factory))
        config = self.request.config.model_copy(update={"provider": "vendor"})
        request = self.request.model_copy(update={"config": config})
        runtime = PydanticAIRuntime()
        try:
            runtime.validate_request(request)
            self.runtime.validate_request(request)
        finally:
            await runtime.aclose()

    async def test_compatible_alias_uses_selected_model_endpoint_and_credentials(
        self,
    ) -> None:
        """Register a compatible provider without adding another conditional branch."""
        from bloomerp.agents.providers.builtins.pydantic_open_ai import (
            create_openai_chat_model,
        )
        from bloomerp.agents.runtimes.pydantic_ai import (
            PydanticAIProvider,
            create_model,
        )

        config = self.request.config.model_copy(
            update={
                "provider": "private_gateway",
                "model": "custom-model",
                "base_url": "https://models.example.test/v1",
            }
        )
        request = self.request.model_copy(update={"config": config})
        self.register_provider(
            "private_gateway", PydanticAIProvider(create_openai_chat_model)
        )
        async with httpx.AsyncClient() as client:
            model = create_model(
                request,
                AgentRuntimeCredentials(api_key="instance-key"),
                client,
            )
            self.assertEqual(model.model_name, "custom-model")
            self.assertEqual(
                str(model.client.base_url), "https://models.example.test/v1/"
            )
            self.assertEqual(model.client.api_key, "instance-key")
            from bloomerp.agents.providers.registry import AI_PROVIDER_REGISTRY

            AI_PROVIDER_REGISTRY.unregister("private_gateway")
            with self.assertRaisesRegex(ValueError, "Unregistered"):
                create_model(
                    request, AgentRuntimeCredentials(api_key="instance-key"), client
                )

    async def test_anthropic_registration_keeps_provider_specific_validation(
        self,
    ) -> None:
        """Retain settings constraints when replacing the provider allow-list."""
        for parameters in ({"seed": 1}, {"openai_reasoning_effort": "high"}):
            config = self.request.config.model_copy(
                update={"provider": "anthropic", "parameters": parameters}
            )
            with self.assertRaises(ValueError):
                self.runtime.validate_request(
                    self.request.model_copy(update={"config": config})
                )

    async def test_pre_refactor_checkpoint_remains_compatible(self) -> None:
        """Restore the original version-one payload shape without migrating state."""
        from bloomerp.agents.runtimes.pydantic_ai import SDK_VERSION

        checkpoint = AgentRuntimeCheckpoint(
            run_id=self.request.run_id,
            context=self.request.context,
            runtime="pydantic_ai",
            runtime_version="1",
            format_version=1,
            config_fingerprint=self.request.config.fingerprint(),
            consumed_message_sequence=1,
            state={
                "sdk_version": SDK_VERSION,
                "history": [],
                "pending": [],
                "queued_messages": [],
                "consumed_sequence": 1,
                "finished": True,
            },
        )
        events = await self.collect(self.resumed(checkpoint))
        self.assertEqual(events[-1].kind, "run.completed")
        self.assertEqual(self.histories, [])
        restored = [
            event.checkpoint for event in events if event.kind == "checkpoint.created"
        ][-1]
        self.assertEqual(restored.state, checkpoint.state)


def test_provider_and_runtime_package_exports_and_defaults() -> None:
    """Expose stable package imports and model-compatible defaults without network discovery."""
    from bloomerp.agents.providers import AI_PROVIDER_REGISTRY
    from bloomerp.agents.providers.builtins.pydantic_ai_common import PydanticAISettings
    from bloomerp.agents.providers.builtins.pydantic_anthropic import AnthropicSettings
    from bloomerp.agents.runtimes import PydanticAIRuntime

    assert AI_PROVIDER_REGISTRY.get("anthropic").config_schema is AnthropicSettings
    assert AI_PROVIDER_REGISTRY.get("openai").config_schema is PydanticAISettings
    assert all(
        AI_PROVIDER_REGISTRY.get(key).description
        for key in ("openai", "openai_chat", "deepseek", "anthropic")
    )
    assert AnthropicSettings().max_tokens == 4096
    assert PydanticAISettings().model_dump(exclude_none=True) == {}
    assert PydanticAIRuntime.__module__ == "bloomerp.agents.runtimes.pydantic_ai"
