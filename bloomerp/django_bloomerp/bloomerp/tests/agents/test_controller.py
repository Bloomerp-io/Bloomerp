"""Exercise persisted controller orchestration with the real offline PydanticAI loop."""

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, DeltaThinkingPart, FunctionModel

from bloomerp.agents.controller import (
    AgentChatRequest,
    AgentController,
    AgentReplayRequest,
)
from bloomerp.agents.runtime import (
    AgentRuntime,
    AgentRuntimeConfig,
    AgentRuntimeCredentials,
    AgentRuntimeEvent,
    AgentRuntimeRunRequest,
    AgentRuntimeToolCoordinator,
)
from bloomerp.agents.runtimes.pydantic_ai import PydanticAIRuntime
from bloomerp.config.definition import BloomerpAgentSettings, BloomerpConfig
from bloomerp.models.agents import AIAgent, AIMessage, AIRun
from bloomerp.models.users.user import AbstractBloomerpUser

OPTIONS = {
    "config": {
        "runtime": "pydantic_ai",
        "provider": "openai",
        "model": "offline",
        "agent_key": "bloomai",
        "agent_version": "1",
    },
    "runtime_factory": "bloomerp.tests.agents.test_controller.offline_runtime",
    "api_key": "never-store-this-secret",
}


def agent_test_config(options: dict[str, object] | None = None) -> BloomerpConfig:
    """Build project settings with offline agent options for integration tests."""
    operations = {
        key: value
        for key, value in (options or {}).items()
        if key in {"mcp_origin", "lease_seconds", "history_limit"}
    }
    return BloomerpConfig(
        bloomai_settings=BloomerpAgentSettings.model_validate(operations)
    )


async def text_stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str]:
    """Produce real SDK streaming events without network requests or tools."""
    yield "Hello "
    yield "from the agent."


async def reasoning_stream(
    messages: list[ModelMessage],
    info: AgentInfo,
) -> AsyncIterator[str | dict[int, DeltaThinkingPart]]:
    """Emit private reasoning before visible text to exercise provider part numbering."""
    yield {
        0: DeltaThinkingPart(content="Private reasoning", signature="private-signature")
    }
    yield "Hello "
    yield "from the agent."


def model_factory(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Select an offline SDK model through the production adapter's factory boundary."""
    return FunctionModel(stream_function=text_stream)


def offline_runtime(config: AgentRuntimeConfig) -> PydanticAIRuntime:
    """Return the real adapter with an offline model for controller integration tests."""
    return PydanticAIRuntime(model_factory=model_factory)


def configure_test_agent(
    user: AbstractBloomerpUser,
    factory: Callable[[AgentRuntimeConfig], AgentRuntime] = offline_runtime,
) -> AIAgent:
    """Create an encrypted offline model and grant only its existing view/use permission."""
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    from bloomerp.agents.providers.builtins.pydantic_ai_common import PydanticAISettings
    from bloomerp.agents.providers.definition import AIProviderDefinition
    from bloomerp.agents.providers.registry import AI_PROVIDER_REGISTRY
    from bloomerp.agents.runtimes.pydantic_ai import PydanticAIProvider
    from bloomerp.models.access_control import (
        FieldPolicy,
        Policy,
        RowPolicy,
        RowPolicyRule,
    )
    from bloomerp.models.agents import AIAgent

    key = "test_" + factory.__name__
    if AI_PROVIDER_REGISTRY.get(key) is None:
        AI_PROVIDER_REGISTRY.register(
            key,
            AIProviderDefinition(
                id=key,
                name=key,
                runtime_factory=factory,
                config_schema=PydanticAISettings,
                integration=PydanticAIProvider(model_factory),
            ),
        )
    model = AIAgent.objects.create(
        name="Offline model", provider=key, model_identifier="offline", created_by=user
    )
    model.set_credentials({"api_key": "never-store-this-secret"})
    model.save()
    content_type = ContentType.objects.get_for_model(AIAgent)
    permission = Permission.objects.get(
        content_type=content_type, codename="view_aiagent"
    )
    row_policy = RowPolicy.objects.create(content_type=content_type)
    rule = RowPolicyRule.objects.create(
        row_policy=row_policy, rule={"connector": "AND", "conditions": []}
    )
    rule.permissions.add(permission)
    field_policy = FieldPolicy.objects.create(
        name="AI picker", content_type=content_type, rule={"__all__": ["view_aiagent"]}
    )
    policy = Policy.objects.create(
        name="Use AI agent", row_policy=row_policy, field_policy=field_policy
    )
    policy.users.add(user)
    policy.global_permissions.add(permission)
    return model


class InterruptedRuntime(PydanticAIRuntime):
    """Simulate process shutdown after a safe checkpoint but before the terminal event."""

    async def execute(
        self,
        request: AgentRuntimeRunRequest,
        *,
        credentials: AgentRuntimeCredentials,
        coordinator: AgentRuntimeToolCoordinator,
    ) -> AsyncIterator[AgentRuntimeEvent]:
        """Forward normal events and interrupt exactly before terminal persistence."""
        stream = super().execute(
            request, credentials=credentials, coordinator=coordinator
        )
        try:
            async for event in stream:
                if event.kind == "run.completed":
                    raise asyncio.CancelledError
                yield event
        finally:
            await stream.aclose()


def interrupted_runtime(config: AgentRuntimeConfig) -> InterruptedRuntime:
    """Build an offline provider that simulates an executor shutdown at a safe boundary."""
    return InterruptedRuntime(model_factory=model_factory)


@override_settings(
    BLOOMERP_CONFIG=agent_test_config(),
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class AgentControllerTests(TestCase):
    """Test cross-layer behavior while keeping model invariants in ModelScenario suites."""

    def setUp(self) -> None:
        """Create separate actors and a stable client submission identity."""
        self.user = get_user_model().objects.create_user(username="controller-owner")
        self.other = get_user_model().objects.create_user(username="controller-other")
        self.ai_agent = configure_test_agent(self.user)
        self.controller = AgentController(self.user, tab_id=uuid4())
        self.request = AgentChatRequest(
            client_message_id=uuid4(), content=[{"type": "text", "text": "Hello"}]
        )

    def test_instance_settings_reject_model_specific_values(self) -> None:
        """Keep model secrets and execution settings out of instance configuration."""
        for values in (
            {"api_key": "secret"},
            {"config": OPTIONS["config"]},
            {"budgets": {"max_tokens": 1}},
        ):
            with self.assertRaises(ValueError):
                BloomerpAgentSettings.model_validate(values)

    def execute_run(self, run: AIRun) -> None:
        """Consume a complete attempt synchronously through the async controller API."""
        async_to_sync(self.controller.run_attempt)(
            run.pk, execution_mode="inline", executor_id="test"
        )
        run.refresh_from_db()

    def test_sync_dispatch_queues_ids_and_sanitizes_broker_failures(self) -> None:
        """HTTP dispatch uses durable IDs and preserves a retryable safe failure state."""
        run = AIRun.objects.get(pk=self.controller.accept_message(self.request).run_id)
        with patch.object(self.controller, "worker_mode", return_value=True):
            with patch(
                "bloomerp.celery.tasks.agent_task.execute_agent_run.delay"
            ) as enqueue:
                self.controller.dispatch_sync(run.pk)
                enqueue.assert_called_once_with(str(run.pk), str(self.user.pk))
            with patch(
                "bloomerp.celery.tasks.agent_task.execute_agent_run.delay",
                side_effect=RuntimeError("private broker credentials"),
            ):
                self.controller.dispatch_sync(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error["code"], "dispatch_failed")
        self.assertNotIn("private broker credentials", str(run.error))

    def test_persists_real_runtime_and_replays_safe_events(self) -> None:
        """Persist a streamed answer, usage and checkpoint, publishing only public events."""
        submission = self.controller.accept_message(self.request)
        run = AIRun.objects.get(pk=submission.run_id)
        self.execute_run(run)
        self.assertEqual(run.status, "completed", run.error)
        output = run.messages.get(role="assistant")
        self.assertEqual(output.content_blocks[0]["text"], "Hello from the agent.")
        self.assertEqual(output.status, "completed")
        self.assertEqual(run.attempts.get().status, "completed")
        self.assertIsNotNone(run.checkpoint)
        self.assertNotIn(
            "never-store-this-secret", str(run.config_snapshot) + str(run.checkpoint)
        )
        replay = async_to_sync(self.controller.replay)(
            AgentReplayRequest(
                conversation_id=run.conversation_id,
                run_id=run.pk,
                limit=1,
            )
        )
        self.assertTrue(replay.has_more)
        self.assertNotEqual(replay.events[0].event_type, "checkpoint.created")
        page = self.controller.replay_page(
            AgentReplayRequest(conversation_id=run.conversation_id, run_id=run.pk)
        )
        self.assertNotIn(
            "checkpoint.created", [event.event_type for event in page.events]
        )
        self.assertEqual(page.events[-1].event_type, "run.completed")
        self.assertEqual(self.controller.accept_message(self.request).run_id, run.pk)
        self.assertEqual(AIRun.objects.count(), 1)
        next_request = self.request.model_copy(
            update={
                "client_message_id": uuid4(),
                "conversation_id": run.conversation_id,
            }
        )
        next_run = AIRun.objects.get(
            pk=self.controller.accept_message(next_request).run_id
        )
        self.execute_run(next_run)
        self.assertEqual(next_run.status, "completed")

    def test_owner_checks_and_conflicting_retry(self) -> None:
        """Reject other owners and altered retry content without writing extra rows."""
        submission = self.controller.accept_message(self.request)
        other = AgentController(self.other)
        with self.assertRaises(PermissionDenied):
            async_to_sync(other.cancel)(submission.run_id)
        with self.assertRaises(PermissionDenied):
            other.replay_page(
                AgentReplayRequest(
                    conversation_id=submission.conversation_id, run_id=submission.run_id
                )
            )
        with self.assertRaises(PermissionDenied):
            other.accept_message(self.request)
        with self.assertRaises(ValidationError):
            self.controller.accept_message(
                AgentChatRequest(
                    client_message_id=self.request.client_message_id,
                    content=[{"type": "text", "text": "Changed"}],
                )
            )
        with self.assertRaises(ValidationError):
            self.controller.accept_message(
                self.request.model_copy(
                    update={
                        "client_message_id": uuid4(),
                        "conversation_id": submission.conversation_id,
                    }
                )
            )
        self.assertEqual(AIMessage.objects.count(), 1)

    def test_cancel_queued_and_expired_recovery(self) -> None:
        """Cancel unclaimed work and recover stale execution without duplicating partial text."""
        run = AIRun.objects.get(pk=self.controller.accept_message(self.request).run_id)
        async_to_sync(self.controller.cancel)(run.pk)
        self.execute_run(run)
        self.assertEqual(run.status, "cancelled")
        self.assertFalse(run.attempts.exists())
        fresh = self.request.model_copy(
            update={
                "client_message_id": uuid4(),
                "conversation_id": run.conversation_id,
            }
        )
        run = AIRun.objects.get(pk=self.controller.accept_message(fresh).run_id)
        old = run.create_attempt(
            execution_mode="inline",
            executor_id="dead",
            lease_duration=timedelta(seconds=10),
        )
        AIMessage.objects.create(
            conversation_id=run.conversation_id,
            run=run,
            role="assistant",
            sequence=3,
            status="streaming",
            content_blocks=[{"type": "text", "text": "Incomplete"}],
        )
        old.lease_expires_at = timezone.now() - timedelta(seconds=1)
        old.save()
        self.execute_run(run)
        self.assertEqual(run.status, "completed", run.error)
        old.refresh_from_db()
        self.assertEqual(old.status, "abandoned")
        self.assertEqual(run.messages.get(sequence=3).status, "interrupted")
        self.assertEqual(run.attempts.count(), 2)

    def test_replay_finishes_pending_cancellation_after_executor_loss(self) -> None:
        """Finish Stop after lease expiry without cancelling live or unrequested work."""
        run = AIRun.objects.get(pk=self.controller.accept_message(self.request).run_id)
        attempt = run.create_attempt(
            execution_mode="inline",
            executor_id="lost-executor",
            lease_duration=timedelta(minutes=1),
        )
        replay_request = AgentReplayRequest(
            conversation_id=run.conversation_id, run_id=run.pk
        )
        async_to_sync(self.controller.cancel)(run.pk)
        run.refresh_from_db()
        requested_at = run.cancel_requested_at
        self.controller.replay_page(replay_request)
        run.refresh_from_db()
        self.assertEqual(run.status, "running")
        self.assertEqual(run.cancel_requested_at, requested_at)

        attempt.lease_expires_at = timezone.now() - timedelta(seconds=1)
        attempt.save()
        page = async_to_sync(self.controller.replay)(replay_request)
        run.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(run.status, "cancelled")
        self.assertEqual(attempt.status, "abandoned")
        self.assertEqual(run.cancel_requested_at, requested_at)
        self.assertEqual(page.events[-1].event_type, "run.cancelled")
        self.controller.replay_page(replay_request)
        self.assertEqual(run.events.filter(event_type="run.cancelled").count(), 1)

        fresh = self.request.model_copy(
            update={
                "client_message_id": uuid4(),
                "conversation_id": run.conversation_id,
            }
        )
        next_run = AIRun.objects.get(pk=self.controller.accept_message(fresh).run_id)
        stale_attempt = next_run.create_attempt(
            execution_mode="inline",
            executor_id="another-lost-executor",
            lease_duration=timedelta(minutes=1),
        )
        stale_attempt.lease_expires_at = timezone.now() - timedelta(seconds=1)
        stale_attempt.save()
        self.controller.replay_page(
            AgentReplayRequest(
                conversation_id=next_run.conversation_id, run_id=next_run.pk
            )
        )
        next_run.refresh_from_db()
        self.assertEqual(next_run.status, "running")
        self.assertIsNone(next_run.cancel_requested_at)

    def test_dispatch_failure_and_worker_payload(self) -> None:
        """Keep worker messages secret-free and record broker failures durably."""
        run = AIRun.objects.get(pk=self.controller.accept_message(self.request).run_id)
        with patch.object(self.controller, "worker_mode", return_value=True):
            with patch(
                "bloomerp.celery.tasks.agent_task.execute_agent_run.delay"
            ) as delay:
                async_to_sync(self.controller.dispatch)(run.pk)
                delay.assert_called_once_with(str(run.pk), str(self.user.pk))
            with patch(
                "bloomerp.celery.tasks.agent_task.execute_agent_run.delay",
                side_effect=RuntimeError("broker-secret"),
            ):
                async_to_sync(self.controller.dispatch)(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertNotIn("broker-secret", str(run.error))

    def test_worker_mode_uses_celery_availability_and_external_broker(self) -> None:
        """Dispatch through workers only when Celery has a shared broker."""
        with (
            patch("bloomerp.celery.utils.is_celery_available", return_value=False),
            override_settings(CELERY_BROKER_URL="redis://localhost:6379/0"),
        ):
            self.assertFalse(self.controller.worker_mode())
        with patch("bloomerp.celery.utils.is_celery_available", return_value=True):
            with override_settings(CELERY_BROKER_URL="memory://"):
                self.assertFalse(self.controller.worker_mode())
            with override_settings(CELERY_BROKER_URL="redis://localhost:6379/0"):
                self.assertTrue(self.controller.worker_mode())

    def test_delivery_failure_does_not_fail_execution(self) -> None:
        """Keep committed output replayable when the channel layer is temporarily down."""
        run = AIRun.objects.get(pk=self.controller.accept_message(self.request).run_id)
        with patch("bloomerp.agents.controller.get_channel_layer") as layer:
            layer.return_value.group_send = AsyncMock(
                side_effect=RuntimeError("delivery failed")
            )
            self.execute_run(run)
        self.assertEqual(run.status, "completed", run.error)
        self.assertTrue(run.events.filter(event_type="run.completed").exists())

    def test_resume_restores_checkpoint_without_repeating_completed_output(
        self,
    ) -> None:
        """Recover the same logical run after shutdown with its provider history intact."""
        run = AIRun.objects.get(pk=self.controller.accept_message(self.request).run_id)
        with (
            patch.object(
                self.controller,
                "get_runtime",
                return_value=interrupted_runtime(run.runtime_config()),
            ),
            self.assertRaises(asyncio.CancelledError),
        ):
            self.execute_run(run)
        run.refresh_from_db()
        self.assertEqual(run.status, "running")
        self.assertTrue(run.checkpoint["state"]["finished"])
        attempt = run.attempts.get()
        attempt.lease_expires_at = timezone.now() - timedelta(seconds=1)
        attempt.save()
        self.execute_run(run)
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(run.messages.filter(role="assistant").count(), 1)
        self.assertEqual(run.attempts.count(), 2)

    def test_reasoning_before_answer_persists_visible_text_only(self) -> None:
        """Persist reasoning-model text using contiguous public block indexes."""
        run = AIRun.objects.get(pk=self.controller.accept_message(self.request).run_id)
        with patch(
            "bloomerp.tests.agents.test_controller.text_stream", reasoning_stream
        ):
            self.execute_run(run)
        self.assertEqual(run.status, "completed", run.error)
        message = run.messages.get(role="assistant")
        self.assertEqual(
            message.content_blocks,
            [{"type": "text", "format": "markdown", "text": "Hello from the agent."}],
        )
        self.assertNotIn(
            "Private reasoning", str(list(run.events.values_list("payload", flat=True)))
        )
        self.assertIn("Private reasoning", str(run.checkpoint))
