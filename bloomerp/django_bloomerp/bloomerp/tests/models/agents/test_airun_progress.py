"""Exercise safe progress, approval gating and lease fencing through model scenarios."""

from datetime import timedelta
from typing import Any
from unittest.mock import Mock

from django.core.exceptions import ValidationError
from django.utils import timezone

from bloomerp.agents.mcp import LocalMcpClient, McpToolCoordinator
from bloomerp.agents.runtime import (
    AgentRuntimeToolProposal,
    AgentRuntimeToolStartedEvent,
)
from bloomerp.models.agents import AIRun, AIToolCall
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)

from ._fixtures import AgentModelFixtures


class TestAirunProgress(AgentModelFixtures, BloomerpModelTestCase):
    """Verify progress describes effects only after they pass the existing approval boundary."""

    model = AIRun

    def get_test_scenarios(self) -> list[ModelScenario[AIRun]]:
        """Declare isolated successful, deferred and invalid progress lifecycles."""
        return self.with_agent_fixtures(
            [
                ModelScenario(
                    name="Tool start is committed and published before dispatch",
                    create_operation=self.execute_tool,
                    create_validators=self.start_is_safe_and_replayable,
                ),
                ModelScenario(
                    name="Waiting approval never claims tool execution",
                    create_operation=self.defer_tool,
                    create_validators=self.wait_has_no_start,
                ),
                ModelScenario(
                    name="Failed live delivery retains replay and does not prevent execution",
                    create_operation=self.execute_without_delivery,
                    create_validators=self.start_is_safe_and_replayable,
                ),
                ModelScenario(
                    name="Waiting tool cannot emit start",
                    create_operation=self.start_waiting_tool,
                    expected_exceptions=[
                        ExpectedModelException(
                            "create", ValidationError, "not executing"
                        )
                    ],
                ),
                ModelScenario(
                    name="Expired lease cannot emit progress",
                    create_operation=self.start_with_expired_lease,
                    expected_exceptions=[
                        ExpectedModelException("create", ValidationError, "lease")
                    ],
                ),
                ModelScenario(
                    name="Progress cannot reference another run's tool",
                    create_operation=self.start_foreign_tool,
                    expected_exceptions=[
                        ExpectedModelException("create", AIToolCall.DoesNotExist)
                    ],
                ),
            ]
        )

    def tool_definition(self, *, read_only: bool) -> dict[str, Any]:
        """Describe a fixture tool whose arguments must remain absent from progress."""
        return {
            "name": "progress_fixture",
            "title": "Read record",
            "description": "Fixture",
            "inputSchema": {
                "type": "object",
                "properties": {"secret": {"type": "string"}},
                "required": ["secret"],
            },
            "annotations": {"readOnlyHint": read_only},
        }

    def execute_tool(
        self, *, read_only: bool = True, delivery_fails: bool = False
    ) -> AIRun:
        """Execute a mock MCP effect and observe its durable progress before dispatch."""
        run = self.make_run()
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="progress-test",
            lease_duration=timedelta(seconds=60),
        )
        definition = self.tool_definition(read_only=read_only)
        client = Mock(spec=LocalMcpClient)
        client.user_id = run.initiated_by_id
        client.catalog.return_value = {definition["name"]: definition}
        client.definition.side_effect = LocalMcpClient.definition
        client.dispatch.side_effect = self.dispatch_after_progress
        publisher = Mock()
        if delivery_fails:
            publisher.side_effect = RuntimeError("fixture delivery failure")
        proposal = AgentRuntimeToolProposal(
            provider_call_id="progress-call",
            tool_identifier=definition["name"],
            tool_version=LocalMcpClient.definition(definition).version,
            arguments={"secret": "hidden-argument"},
        )
        self.progress_run = run
        self.progress_client = client
        self.progress_publisher = publisher
        self.progress_outcome = McpToolCoordinator(
            run, attempt, client, publish=publisher
        ).execute(proposal)
        return run

    def dispatch_after_progress(
        self, proposal: AgentRuntimeToolProposal
    ) -> dict[str, Any]:
        """Verify status is already observable at the exact effect boundary."""
        event = self.progress_run.events.get(event_type="tool.started")
        self.assertEqual(event.payload["data"], {"tool_title": "Read record"})
        self.progress_publisher.assert_called_once()
        return {"content": []}

    def defer_tool(self) -> AIRun:
        """Request a writing tool subject to the conversation's approval policy."""
        return self.execute_tool(read_only=False)

    def execute_without_delivery(self) -> AIRun:
        """Simulate a disconnected subscriber while retaining the committed progress event."""
        return self.execute_tool(delivery_fails=True)

    def start_is_safe_and_replayable(self, run: AIRun) -> bool:
        """Check the start event and transcript snapshot expose only operational metadata."""
        self.assertEqual(self.progress_outcome.status, "completed")
        self.progress_client.dispatch.assert_called_once()
        event = run.events.get(event_type="tool.started")
        self.assertEqual(
            event.public_payload()["payload"]["data"], {"tool_title": "Read record"}
        )
        with run.locked() as locked:
            locked.append_event(
                "checkpoint.created", {"data": {"private": "hidden-reasoning"}}
            )
        snapshot = run.conversation.transcript_page()["run"]["progress"]
        self.assertEqual(
            snapshot,
            {
                "sequence": event.sequence,
                "event_type": "tool.started",
                "payload": {"data": {"tool_title": "Read record"}},
            },
        )
        self.assertNotIn("hidden-argument", str(snapshot))
        self.assertNotIn("hidden-reasoning", str(snapshot))
        return True

    def wait_has_no_start(self, run: AIRun) -> bool:
        """Verify an approval wait produces neither a start event nor an effect."""
        self.assertEqual(self.progress_outcome.status, "waiting")
        self.progress_client.dispatch.assert_not_called()
        self.progress_publisher.assert_not_called()
        self.assertFalse(run.events.filter(event_type="tool.started").exists())
        return True

    def start_waiting_tool(self) -> AIRun:
        """Attempt to announce a tool which has not passed its approval wait."""
        run = self.make_run()
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="test",
            lease_duration=timedelta(seconds=60),
        )
        tool = self.make_tool(run, status="waiting")
        run.apply_runtime_event(
            AgentRuntimeToolStartedEvent(
                run_id=run.pk, attempt_id=attempt.pk, tool_call_id=tool.pk
            ),
            lease_token=attempt.lease_token,
        )
        return run

    def start_with_expired_lease(self) -> AIRun:
        """Fence progress from an executor whose lease has expired."""
        run = self.make_run()
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="test",
            lease_duration=timedelta(seconds=60),
        )
        tool = self.make_tool(run, status="running")
        attempt.lease_expires_at = timezone.now() - timedelta(seconds=1)
        attempt.save()
        run.apply_runtime_event(
            AgentRuntimeToolStartedEvent(
                run_id=run.pk, attempt_id=attempt.pk, tool_call_id=tool.pk
            ),
            lease_token=attempt.lease_token,
        )
        return run

    def start_foreign_tool(self) -> AIRun:
        """Reject a start reference outside the executor's logical run."""
        run = self.make_run()
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="test",
            lease_duration=timedelta(seconds=60),
        )
        foreign = self.make_run(
            conversation=self.other_conversation,
            trigger_message=None,
            trigger_type="schedule",
            initiated_by=self.other_user,
        )
        tool = self.make_tool(foreign, status="running")
        run.apply_runtime_event(
            AgentRuntimeToolStartedEvent(
                run_id=run.pk, attempt_id=attempt.pk, tool_call_id=tool.pk
            ),
            lease_token=attempt.lease_token,
        )
        return run
