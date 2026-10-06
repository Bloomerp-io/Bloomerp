"""Declarative lifecycle scenarios for AIRunAttempt persistence."""

from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone

from bloomerp.models.agents import AIRunAttempt
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)

from ._fixtures import AgentModelFixtures


class TestAirunAttemptModel(AgentModelFixtures, BloomerpModelTestCase):
    """Exercise active-attempt exclusivity and inline-to-worker continuation."""

    model = AIRunAttempt

    def get_test_scenarios(self) -> list[ModelScenario[AIRunAttempt]]:
        """Declare separate concurrency and successful resumption scenarios."""
        return self.with_agent_fixtures(
            [
                ModelScenario(
                    name="A run cannot have two active attempts",
                    create_args=self.conflicting_args,
                    expected_exceptions=[
                        ExpectedModelException(
                            "create", ValidationError, "ai_one_active_attempt"
                        )
                    ],
                ),
                ModelScenario(
                    name="Paused inline attempt resumes in a worker",
                    create_args=self.initial_args,
                    post_create=self.attach_tool,
                    update_args=self.paused_args,
                    update_validators=self.worker_retains_provenance,
                ),
            ]
        )

    def initial_args(self) -> dict[str, Any]:
        """Prepare the first leased executor for a fresh logical run."""
        return self.attempt_args(self.make_run())

    def conflicting_args(self) -> dict[str, Any]:
        """Keep one executor running while proposing a second executor."""
        run = self.make_run()
        self.make_attempt(run)
        return self.attempt_args(run, number=2)

    def attach_tool(self, attempt: AIRunAttempt) -> None:
        """Record the original dispatch before the framework pauses the attempt."""
        self.tool = self.make_tool(attempt.run, first_dispatch_attempt=attempt)

    def paused_args(self) -> dict[str, Any]:
        """End the current execution period without completing its logical run."""
        return {"status": "paused", "finished_at": timezone.now()}

    def worker_retains_provenance(self, attempt: AIRunAttempt) -> bool:
        """Create the resumed worker and verify original tool dispatch remains intact."""
        resumed = self.make_attempt(attempt.run, number=2, execution_mode="worker")
        self.tool.refresh_from_db()
        return (
            self.tool.run_id == resumed.run_id
            and self.tool.first_dispatch_attempt_id == attempt.pk
            and resumed.execution_mode == "worker"
        )
