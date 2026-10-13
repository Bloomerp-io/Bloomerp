"""Test lifecycle guarantees with a tiny adapter that has no provider SDK."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from collections.abc import AsyncIterator
from unittest import IsolatedAsyncioTestCase
from uuid import UUID, uuid4

from pydantic import Field

from bloomerp.agents.runtime import (
    AgentRuntimeAttempt,
    AgentRuntimeCheckpoint,
    AgentRuntimeCredentials,
    AgentRuntimeEvent,
    AgentRuntimePendingToolProposal,
    AgentRuntimeResumeRequest,
    AgentRuntimeRunFinishedEvent,
    AgentRuntimeRunPausedEvent,
    AgentRuntimeRunRequest,
    AgentRuntimeState,
    AgentRuntimeToolCoordinator,
    AgentRuntimeToolOutcome,
    AgentRuntimeToolProposal,
    BaseAgentRuntime,
)


class ExampleState(AgentRuntimeState):
    """Represent a second framework's simple serializable continuation."""

    results: list[str] = Field(default_factory=list)


class ExampleRuntime(BaseAgentRuntime[ExampleState]):
    """Exercise the base lifecycle using no model library or network client."""

    runtime_name = "example"
    runtime_version = "1"

    def __init__(
        self, *, blocked: bool = False, failure: Exception | None = None
    ) -> None:
        """Choose whether execution completes, waits, or raises a test failure."""
        super().__init__()
        self.blocked = blocked
        self.failure = failure
        self.entered = asyncio.Event()
        self.released = asyncio.Event()

    def _validate_request(self, request: AgentRuntimeRunRequest) -> None:
        """Accept all example model configurations after the shared checks."""
        return

    def _initial_state(self, request: AgentRuntimeRunRequest) -> ExampleState:
        """Create one portable proposal when a tool is present in the catalog."""
        state = ExampleState()
        if request.tools:
            tool = request.tools[0]
            state.pending.append(
                AgentRuntimePendingToolProposal(
                    proposal=AgentRuntimeToolProposal(
                        provider_call_id="call-1",
                        tool_identifier=tool.identifier,
                        tool_version=tool.version,
                        arguments={},
                    )
                )
            )
        return state

    def _restore_state(self, checkpoint: AgentRuntimeCheckpoint) -> ExampleState:
        """Decode only this adapter's simple checkpoint payload."""
        return ExampleState.model_validate(checkpoint.state)

    def _add_messages(
        self, request: AgentRuntimeRunRequest, state: ExampleState
    ) -> None:
        """Restart the example turn when new transcript input arrives."""
        if request.messages:
            state.finished = False

    def _apply_tool_results(self, state: ExampleState) -> None:
        """Record translated outcomes after the base resolves the whole batch."""
        for call in state.pending:
            assert call.outcome is not None
            state.results.append(call.outcome.status)

    async def _run(
        self,
        attempt: AgentRuntimeAttempt,
        state: ExampleState,
        credentials: AgentRuntimeCredentials,
        coordinator: AgentRuntimeToolCoordinator,
    ) -> AgentRuntimeRunFinishedEvent | AgentRuntimeRunPausedEvent:
        """Run a tiny framework loop through the shared checkpoint/tool boundaries."""
        try:
            await self._save(attempt, state)
            self.entered.set()
            if self.blocked:
                await asyncio.Event().wait()
            if self.failure is not None:
                raise self.failure
            if state.pending:
                paused = await self._dispatch(attempt, state, coordinator)
                if paused is not None:
                    return paused
            state.finished = True
            attempt.record_tokens(input_tokens=3, output_tokens=2)
            await self._save(attempt, state)
            return AgentRuntimeRunFinishedEvent(
                run_id=attempt.request.run_id,
                attempt_id=attempt.request.attempt_id,
                kind="run.completed",
                usage=attempt.usage(),
            )
        finally:
            self.released.set()


class ExampleCoordinator:
    """Emulate durable action state independently of any SDK tool representation."""

    def __init__(self, *, waiting: bool = False) -> None:
        """Create stable identities and counters for coordinator invocations."""
        self.waiting = waiting
        self.call_id = uuid4()
        self.approval_id = uuid4()
        self.calls = 0
        self.resolutions = 0

    def _outcome(self) -> AgentRuntimeToolOutcome:
        """Expose the current action result or outstanding approval requirement."""
        return AgentRuntimeToolOutcome(
            tool_call_id=self.call_id,
            provider_call_id="call-1",
            status="waiting" if self.waiting else "completed",
            result=None if self.waiting else {},
            approval_ids=(self.approval_id,) if self.waiting else (),
        )

    async def call(self, proposal: AgentRuntimeToolProposal) -> AgentRuntimeToolOutcome:
        """Record a proposal under its original stable provider identifier."""
        self.calls += 1
        return self._outcome()

    async def resolve(self, tool_call_id: UUID) -> AgentRuntimeToolOutcome:
        """Read approval resolution without re-executing the original action."""
        self.resolutions += 1
        return self._outcome()


class BaseAgentRuntimeTests(IsolatedAsyncioTestCase):
    """Verify shared behavior using a second, SDK-independent implementation."""

    def setUp(self) -> None:
        """Construct minimal configuration and one permission-filtered tool."""
        self.runtime = ExampleRuntime()
        self.coordinator = ExampleCoordinator()
        self.request = AgentRuntimeRunRequest(
            run_id=uuid4(),
            attempt_id=uuid4(),
            config={
                "runtime": "example",
                "provider": "example",
                "model": "example",
                "agent_key": "example",
                "agent_version": "1",
            },
            context={
                "user_id": "1",
                "conversation_id": uuid4(),
            },
            tools=(
                {
                    "identifier": "lookup",
                    "version": "1",
                    "description": "Lookup",
                    "input_schema": {"type": "object"},
                },
            ),
        )

    async def asyncTearDown(self) -> None:
        """Cancel any unfinished test attempt and release resources."""
        await self.runtime.aclose()

    def stream(
        self, request: AgentRuntimeRunRequest | AgentRuntimeResumeRequest
    ) -> AsyncIterator[AgentRuntimeEvent]:
        """Dispatch a portable request through the inherited public interface."""
        if isinstance(request, AgentRuntimeResumeRequest):
            return self.runtime.resume(
                request,
                credentials=AgentRuntimeCredentials(),
                coordinator=self.coordinator,
            )
        return self.runtime.execute(
            request, credentials=AgentRuntimeCredentials(), coordinator=self.coordinator
        )

    async def collect(
        self, request: AgentRuntimeRunRequest | AgentRuntimeResumeRequest
    ) -> list[AgentRuntimeEvent]:
        """Consume and acknowledge every event as a durable runner would."""
        return [event async for event in self.stream(request)]

    def test_base_is_abstract(self) -> None:
        """Require framework hooks instead of inheriting protocol no-op methods."""
        with self.assertRaises(TypeError):
            BaseAgentRuntime()

    def test_base_import_does_not_load_provider_sdks(self) -> None:
        """Keep the reusable base importable without initializing a model framework."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import bloomerp.agents.runtime; "
                    "assert not {'pydantic_ai', 'openai', 'anthropic', 'django'} & sys.modules.keys()"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    async def test_checkpoint_backpressure_prevents_tool_execution(self) -> None:
        """Wait for caller acknowledgment before executing a checkpointed proposal."""
        stream = self.stream(self.request)
        await anext(stream)
        checkpoint = await anext(stream)
        self.assertEqual(checkpoint.kind, "checkpoint.created")
        await asyncio.sleep(0)
        self.assertEqual(self.coordinator.calls, 0)
        await stream.aclose()
        self.assertTrue(self.runtime.released.is_set())

    async def test_approval_pause_resume_uses_portable_tool_outcomes(self) -> None:
        """Resolve an approval under a new attempt without re-proposing the effect."""
        self.coordinator.waiting = True
        first = await self.collect(self.request)
        paused = first[-1]
        self.assertEqual(paused.kind, "run.paused")
        self.assertEqual(paused.checkpoint.runtime, "example")
        self.assertEqual(
            paused.checkpoint.pending_tool_call_ids, (self.coordinator.call_id,)
        )
        self.coordinator.waiting = False
        resumed = AgentRuntimeResumeRequest(
            run=self.request.model_copy(
                update={"attempt_id": uuid4(), "usage": paused.usage}
            ),
            checkpoint=AgentRuntimeCheckpoint.model_validate_json(
                paused.checkpoint.model_dump_json()
            ),
        )
        events = await self.collect(resumed)
        self.assertEqual(events[-1].kind, "run.completed")
        self.assertEqual(self.coordinator.calls, 1)
        self.assertEqual(self.coordinator.resolutions, 1)
        checkpoint = [
            event.checkpoint for event in events if event.kind == "checkpoint.created"
        ][-1]
        self.assertEqual(checkpoint.state["results"], ["completed"])
        self.assertEqual(checkpoint.state["pending"], [])
        self.assertEqual(events[-1].usage.tool_calls, 0)

    async def test_tool_budget_includes_prior_attempt_usage(self) -> None:
        """Reject dispatch when the logical run has exhausted its action budget."""
        request = AgentRuntimeRunRequest.model_validate(
            self.request.model_dump()
            | {
                "budgets": {"max_tool_calls": 1},
                "usage": {"tool_calls": 1},
            }
        )
        events = await self.collect(request)
        self.assertEqual(events[-1].error.code, "budget_exceeded")
        self.assertEqual(self.coordinator.calls, 0)

    async def test_deadline_releases_adapter_resources(self) -> None:
        """Interrupt a blocked framework when its remaining lifetime duration expires."""
        self.runtime = ExampleRuntime(blocked=True)
        request = AgentRuntimeRunRequest.model_validate(
            self.request.model_dump()
            | {
                "budgets": {"max_duration_seconds": 1},
                "usage": {"duration_seconds": 0.98},
            }
        )
        events = await asyncio.wait_for(self.collect(request), 2)
        self.assertEqual(events[-1].error.code, "budget_exceeded")
        self.assertTrue(self.runtime.released.is_set())

    async def test_cancel_targets_exact_attempt_and_wakes_consumer(self) -> None:
        """Keep cancellation local to one attempt and emit a single terminal event."""
        self.runtime = ExampleRuntime(blocked=True)
        consumer = asyncio.create_task(self.collect(self.request))
        await asyncio.wait_for(self.runtime.entered.wait(), 2)
        await self.runtime.cancel(self.request.run_id, attempt_id=uuid4())
        self.assertFalse(consumer.done())
        await self.runtime.cancel(
            self.request.run_id, attempt_id=self.request.attempt_id
        )
        events = await asyncio.wait_for(consumer, 2)
        self.assertEqual(events[-1].kind, "run.cancelled")
        self.assertTrue(self.runtime.released.is_set())

    async def test_failure_is_sanitized(self) -> None:
        """Keep arbitrary framework exception content out of persistence events."""
        self.runtime = ExampleRuntime(failure=RuntimeError("private-key"))
        events = await self.collect(self.request)
        self.assertEqual(events[-1].kind, "run.failed")
        self.assertNotIn("private-key", events[-1].model_dump_json())
        self.assertTrue(self.runtime.released.is_set())

    async def test_resume_rejects_invalid_shared_checkpoint_metadata(self) -> None:
        """Validate envelopes before the restored adapter can execute any actions."""
        self.coordinator.waiting = True
        events = await self.collect(self.request)
        original = events[-1].checkpoint
        for changed in (
            {"runtime_version": "unknown"},
            {"consumed_message_sequence": 9},
            {"pending_tool_call_ids": ()},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.stream(
                    AgentRuntimeResumeRequest(
                        run=self.request.model_copy(update={"attempt_id": uuid4()}),
                        checkpoint=original.model_copy(update=changed),
                    )
                )
        self.assertEqual(self.coordinator.resolutions, 0)
