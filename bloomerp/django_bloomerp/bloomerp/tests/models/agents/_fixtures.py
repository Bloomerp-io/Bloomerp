"""Shared fixtures for generated agent model tests; no standalone test case."""

from datetime import timedelta
from typing import Any
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

from bloomerp.models.agents import (
    AIArtifact,
    AIConversation,
    AIMessage,
    AIRun,
    AIRunAttempt,
    AIToolCall,
)
from bloomerp.tests.base import ModelScenario


class AgentModelFixtures:
    """Build related records while preserving the generated model test base class."""

    def prepare_agent_records(self) -> None:
        """Create fresh related records inside each scenario rollback boundary."""
        self.user = get_user_model().objects.create_user(username="agent-owner")
        self.other_user = get_user_model().objects.create_user(username="agent-other")
        self.conversation = AIConversation.objects.create(owner=self.user)
        self.other_conversation = AIConversation.objects.create(owner=self.other_user)
        self.message = AIMessage.objects.create(
            conversation=self.conversation,
            sequence=1,
            role="user",
            content_blocks=[{"type": "text", "text": "Analyze revenue"}],
        )

    def run_args(self, **overrides: Any) -> dict[str, Any]:
        """Describe a queued message-triggered run with a provider-neutral config."""
        values = {
            "conversation": self.conversation,
            "trigger_message": self.message,
            "initiated_by": self.user,
            "agent_key": "bloomai",
            "agent_version": "1",
            "config_snapshot": {"runtime": "test", "provider": "test", "model": "test"},
        }
        values.update(overrides)
        return values

    def make_run(self, **overrides: Any) -> AIRun:
        """Create a related run for another model's lifecycle scenario."""
        return AIRun.objects.create(**self.run_args(**overrides))

    def attempt_args(self, run: AIRun, **overrides: Any) -> dict[str, Any]:
        """Describe a currently leased inline execution attempt."""
        now = timezone.now()
        values = {
            "run": run,
            "number": 1,
            "execution_mode": "inline",
            "executor_id": "test",
            "lease_token": uuid4(),
            "lease_expires_at": now + timedelta(minutes=5),
            "heartbeat_at": now,
            "started_at": now,
        }
        values.update(overrides)
        return values

    def make_attempt(self, run: AIRun, **overrides: Any) -> AIRunAttempt:
        """Create a related execution attempt with a valid lease."""
        return AIRunAttempt.objects.create(**self.attempt_args(run, **overrides))

    def tool_args(self, run: AIRun, **overrides: Any) -> dict[str, Any]:
        """Describe a stable tool proposal whose arguments become immutable."""
        return {
            "run": run,
            "tool_identifier": "navigate",
            "tool_version": "1",
            "provider_call_id": "call-1",
            "arguments": {"path": "/customers/"},
            **overrides,
        }

    def make_tool(self, run: AIRun, **overrides: Any) -> AIToolCall:
        """Create a related proposal for approval and provenance scenarios."""
        return AIToolCall.objects.create(**self.tool_args(run, **overrides))

    def approval_args(self, tool: AIToolCall, **overrides: Any) -> dict[str, Any]:
        """Describe an approval bound to the exact tool proposal."""
        values = {
            "tool_call": tool,
            "requirement_snapshot": {
                "rule_key": "owner",
                "rule_version": "1",
                "mode": "conversation_owner",
            },
            "proposal_snapshot": {
                "tool_identifier": tool.tool_identifier,
                "tool_version": tool.tool_version,
                "arguments": tool.arguments,
            },
        }
        values.update(overrides)
        return values

    def chart_args(self, **overrides: Any) -> dict[str, Any]:
        """Describe an analytics artifact using the existing tile contract."""
        values = {
            "conversation": self.conversation,
            "kind": "analytics",
            "payload": {
                "kind": "analytics",
                "config": {"query": "SELECT 1 AS revenue", "type": "table"},
            },
        }
        values.update(overrides)
        return values

    def make_chart(self, **overrides: Any) -> AIArtifact:
        """Create a related analytics artifact using the tile schema."""
        return AIArtifact.objects.create(**self.chart_args(**overrides))

    def model_is_internal(self, instance: models.Model) -> bool:
        """Check successful scenario records stay outside the generated API catalog."""
        from bloomerp.views.api.generic.base import get_auto_api_models

        config = type(instance).bloomerp_config
        return (
            config.is_internal
            and type(instance) not in get_auto_api_models()
            and not config.should_enable_api_auto_generation()
            and not config.string_search_settings.allow_global_search
        )

    def with_agent_fixtures[ModelT: models.Model](
        self,
        scenarios: list[ModelScenario[ModelT]],
    ) -> list[ModelScenario[ModelT]]:
        """Attach isolated preparation and shared visibility checks to each scenario."""
        for scenario in scenarios:
            scenario.preparation = self.prepare_agent_records
            validators = scenario.create_validators
            scenario.create_validators = (
                [validators] if callable(validators) else list(validators)
            ) + [self.model_is_internal]
        return scenarios
