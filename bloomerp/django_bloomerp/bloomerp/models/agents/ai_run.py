"""Durable logical executions, independent of any worker lifetime."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Literal
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone

from bloomerp.agents.definition import AgentError, MessageContent, RunUsage
from bloomerp.agents.runtime import AgentRuntimeCheckpoint, AgentRuntimeConfig

from .base import AgentModel
from .fields import AgentJSONField

if TYPE_CHECKING:
    from bloomerp.agents.runtime import AgentRuntimeEvent

    from .ai_run_attempt import AIRunAttempt
    from .ai_run_event import AIRunEvent


class AIRun(AgentModel):
    """Persist one task across inline or worker attempts, waits, and retries."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        WAITING = "waiting", "Waiting"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class TriggerType(models.TextChoices):
        MESSAGE = "message", "Message"
        SCHEDULE = "schedule", "Schedule"
        EVENT = "event", "External event"

    immutable_fields = (
        "conversation_id",
        "trigger_message_id",
        "trigger_type",
        "trigger_context",
        "initiated_by_id",
        "agent_key",
        "agent_version",
        "config_snapshot",
        "origin_browser_context",
    )
    conversation = models.ForeignKey(
        "bloomerp.AIConversation", on_delete=models.CASCADE, related_name="runs"
    )
    trigger_message = models.ForeignKey(
        "bloomerp.AIMessage",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="triggered_runs",
    )
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.RESTRICT,
        related_name="initiated_ai_runs",
    )
    trigger_type = models.CharField(
        max_length=16, choices=TriggerType.choices, default=TriggerType.MESSAGE
    )
    trigger_context = AgentJSONField(default=dict, blank=True)
    agent_key = models.CharField(max_length=100)
    agent_version = models.CharField(max_length=100)
    config_snapshot = AgentJSONField(schema="config.v1")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED
    )
    origin_browser_context = AgentJSONField(schema="browser.v1", null=True, blank=True)
    checkpoint = AgentJSONField(null=True, blank=True)
    checkpoint_runtime = models.CharField(max_length=100, blank=True)
    checkpoint_version = models.PositiveIntegerField(default=1)
    consumed_message_sequence = models.PositiveBigIntegerField(default=0)
    wait_condition = AgentJSONField(schema="wait.v1", null=True, blank=True)
    resume_after = models.DateTimeField(null=True, blank=True)
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    budgets = AgentJSONField(schema="budgets.v1", default=dict, blank=True)
    usage = AgentJSONField(schema="usage.v1", default=dict, blank=True)
    error = AgentJSONField(schema="error.v1", null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta(AgentModel.Meta):
        db_table = "bloomerp_ai_run"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["conversation"],
                condition=models.Q(status__in=["queued", "running", "waiting"]),
                name="ai_one_unfinished_run",
            ),
            models.CheckConstraint(
                condition=models.Q(checkpoint_version__gte=1),
                name="ai_checkpoint_version_positive",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "resume_after"], name="ai_run_wakeup")
        ]

    def clean(self) -> None:
        """Validate triggering provenance and resumable checkpoint metadata."""
        super().clean()
        if self.trigger_message_id:
            self.check_conversation(
                "trigger_message",
                self.trigger_message.conversation_id,
                self.conversation_id,
            )
        if (
            self.trigger_type == self.TriggerType.MESSAGE
            and not self.trigger_message_id
        ):
            raise ValidationError(
                {
                    "trigger_message": "Message-triggered runs require a triggering message."
                }
            )
        if self.checkpoint is not None and not self.checkpoint_runtime:
            raise ValidationError(
                {"checkpoint_runtime": "A checkpoint requires its runtime identifier."}
            )
        if self.status == self.Status.WAITING and self.wait_condition is None:
            raise ValidationError(
                {"wait_condition": "Waiting runs require a wake condition."}
            )

    @contextmanager
    def locked(self) -> Iterator[AIRun]:
        """Lock conversation before run consistently across sequence and lease operations."""
        from .ai_conversation import AIConversation

        with transaction.atomic():
            AIConversation.objects.select_for_update().get(pk=self.conversation_id)
            yield (
                type(self)
                .objects.select_for_update()
                .select_related("conversation")
                .get(pk=self.pk)
            )

    def runtime_config(self) -> AgentRuntimeConfig:
        """Restore the non-secret configuration pinned at run creation."""
        return AgentRuntimeConfig(
            **self.config_snapshot,
            agent_key=self.agent_key,
            agent_version=self.agent_version,
        )

    def create_attempt(
        self,
        *,
        execution_mode: Literal["inline", "worker"],
        executor_id: str,
        lease_duration: timedelta,
    ) -> AIRunAttempt:
        """Claim runnable work; fence and abandon any expired executor before retrying."""
        from .ai_run_attempt import AIRunAttempt

        if lease_duration.total_seconds() <= 0:
            raise ValidationError("Lease must be positive")
        with self.locked() as run:
            now = timezone.now()
            if run.status not in {"queued", "running"} or run.cancel_requested_at:
                raise ValidationError("Run is not runnable")
            for old in run.attempts.filter(status="running"):
                if old.lease_expires_at > now:
                    raise ValidationError("Run already has an active lease")
                old.status, old.finished_at = "abandoned", now
                old.save()
                run.finish_messages("interrupted")
            number = (run.attempts.aggregate(last=Max("number"))["last"] or 0) + 1
            attempt = AIRunAttempt.objects.create(
                run=run,
                number=number,
                execution_mode=execution_mode,
                executor_id=executor_id,
                lease_token=uuid4(),
                usage=RunUsage(),
                lease_expires_at=now + lease_duration,
                heartbeat_at=now,
                started_at=now,
            )
            run.status = "running"
            run.wait_condition = None
            run.resume_after = None
            run.save()
            return attempt

    def leased_attempt(self, token: UUID) -> AIRunAttempt:
        """Validate a live executor token while the caller holds the run lock."""
        attempt = self.attempts.filter(lease_token=token, status="running").first()
        if (
            attempt is None
            or attempt.lease_expires_at <= timezone.now()
            or self.status != "running"
        ):
            raise ValidationError("Run lease is stale")
        return attempt

    def heartbeat(self, token: UUID, *, lease_duration: timedelta) -> bool:
        """Renew a live lease and return the durable cancellation flag."""
        if lease_duration.total_seconds() <= 0:
            raise ValidationError("Lease must be positive")
        with self.locked() as run:
            attempt = run.leased_attempt(token)
            attempt.heartbeat_at = timezone.now()
            attempt.lease_expires_at = attempt.heartbeat_at + lease_duration
            attempt.save()
            return run.cancel_requested_at is not None

    def finish_messages(self, status: str) -> None:
        """Finalize provisional output under the caller's conversation/run transaction."""
        for message in self.messages.filter(status="streaming"):
            message.status = status
            message.save()

    def progress_snapshot(self) -> dict[str, Any] | None:
        """Restore the latest observable stage without including arguments, results or checkpoints."""
        event = self.events.filter(
            event_type__in=["tool.started", "tool.outcome", "text.delta", "run.paused", "approval.decided"]
        ).order_by("-sequence").first()
        if event is None:
            return None
        data = event.payload.get("data", {})
        return {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "payload": {"data": {key: data[key] for key in ("tool_title", "status", "wait_kind") if key in data}},
        }

    def append_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        attempt: AIRunAttempt | None = None,
    ) -> AIRunEvent:
        """Allocate a durable event sequence while holding the run lock."""
        from .ai_run_event import AIRunEvent

        sequence = (self.events.aggregate(last=Max("sequence"))["last"] or 0) + 1
        return AIRunEvent.objects.create(
            run=self,
            attempt=attempt,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
        )

    def stop_pending_tools(self) -> None:
        """Close unexecuted approvals and flag in-flight effects for reconciliation under the run lock."""
        from .ai_approval import AIApproval

        for approval in AIApproval.objects.filter(
            tool_call__run=self, status="pending"
        ):
            approval.status = "cancelled"
            approval.save()
        for tool in self.tool_calls.filter(
            status__in=["proposed", "waiting", "running"]
        ):
            tool.status = "unknown" if tool.status == "running" else "cancelled"
            tool.finished_at = timezone.now()
            tool.save()

    def queue_after_approvals(self) -> bool:
        """Queue a paused run when all its persisted decisions are resolved, under its lock."""
        from .ai_approval import AIApproval

        if self.status != "waiting" or self.cancel_requested_at:
            return False
        if not self.wait_condition or self.wait_condition.get("kind") != "approval":
            return False
        if AIApproval.objects.filter(tool_call__run=self, status="pending").exists():
            return False
        self.status = "queued"
        self.wait_condition = None
        self.save()
        return True

    def request_cancel(self) -> AIRunEvent | None:
        """Record cancellation atomically, terminating immediately when no live executor exists."""
        with self.locked() as run:
            if run.status in {"completed", "cancelled", "failed"}:
                return None
            run.cancel_requested_at = run.cancel_requested_at or timezone.now()
            active = run.attempts.filter(
                status="running", lease_expires_at__gt=timezone.now()
            ).exists()
            if active:
                run.save()
                return None
            for attempt in run.attempts.filter(status="running"):
                attempt.status, attempt.finished_at = "abandoned", timezone.now()
                attempt.save()
            run.status, run.finished_at = "cancelled", timezone.now()
            run.wait_condition = None
            run.finish_messages("interrupted")
            run.stop_pending_tools()
            run.save()
            return run.append_event("run.cancelled", {})

    def fail_queued(self, error: AgentError) -> AIRunEvent | None:
        """Persist dispatch failure only if no executor has already claimed the run."""
        with self.locked() as run:
            if run.status != "queued":
                return None
            run.status, run.finished_at = "failed", timezone.now()
            run.error = error.model_dump(mode="json")
            run.save()
            return run.append_event("run.failed", {"data": {"error": run.error}})

    def apply_runtime_event(
        self, event: AgentRuntimeEvent, *, lease_token: UUID
    ) -> AIRunEvent:
        """Persist fenced progress, text, usage, checkpoints and terminal state atomically."""
        from .ai_message import AIMessage

        with self.locked() as run:
            attempt = run.leased_attempt(lease_token)
            if event.run_id != run.pk or event.attempt_id != attempt.pk:
                raise ValidationError("Runtime event belongs to another execution")
            kind = event.kind
            payload = {"data": {}}
            if kind == "text.delta":
                message = AIMessage.objects.filter(pk=event.message_id).first()
                if message is None:
                    message = run.conversation.append_message(
                        message_id=event.message_id,
                        run=run,
                        role="assistant",
                        content=MessageContent(root=[]),
                        status="streaming",
                    )
                if (
                    message.run_id != run.pk
                    or message.role != "assistant"
                    or message.status != "streaming"
                ):
                    raise ValidationError("Invalid runtime message identity")
                blocks = message.content_blocks
                if event.block_index > len(blocks):
                    raise ValidationError("Text blocks must arrive in order")
                if event.block_index == len(blocks):
                    blocks.append({"type": "text", "format": event.format, "text": ""})
                if blocks[event.block_index]["format"] != event.format:
                    raise ValidationError("Text format changed within a block")
                blocks[event.block_index]["text"] += event.text
                message.content_blocks = blocks
                message.save()
                payload = {
                    "message_id": str(message.pk),
                    "text": event.text,
                    "data": {"block_index": event.block_index, "format": event.format},
                }
            elif kind == "tool.started":
                tool = run.tool_calls.get(pk=event.tool_call_id)
                if tool.status != "running" or tool.first_dispatch_attempt_id != attempt.pk:
                    raise ValidationError("Tool is not executing")
                payload = {
                    "tool_call_id": str(tool.pk),
                    "data": {"tool_title": tool.display_title()},
                }
            elif kind == "tool.outcome":
                tool = run.tool_calls.get(pk=event.outcome.tool_call_id)
                if tool.provider_call_id != event.outcome.provider_call_id:
                    raise ValidationError("Tool outcome identity mismatch")
                payload = {
                    "tool_call_id": str(tool.pk),
                    "data": {
                        "status": tool.status,
                        "tool_identifier": tool.tool_identifier,
                        "tool_title": tool.display_title(),
                        "artifacts": [
                            {"id": str(link.artifact_id), "created_at": artifact_message.datetime_created.isoformat()}
                            for artifact_message in run.conversation.messages.filter(
                                artifact_links__artifact__created_by_tool_call=tool
                            ).prefetch_related("artifact_links").all()
                            for link in artifact_message.artifact_links.all()
                        ],
                        "approvals": [
                            {
                                "id": str(approval.pk),
                                "status": approval.status,
                                "tool_identifier": tool.tool_identifier,
                                "tool_title": tool.display_title(),
                                "arguments": tool.arguments,
                            }
                            for approval in tool.approvals.all()
                        ],
                    },
                }
            elif kind not in {
                "usage.updated",
                "checkpoint.created",
                "run.completed",
                "run.cancelled",
                "run.failed",
                "run.paused",
            }:
                raise ValidationError("Unsupported runtime event")
            if hasattr(event, "checkpoint"):
                checkpoint = AgentRuntimeCheckpoint.model_validate(event.checkpoint)
                if (
                    checkpoint.config_fingerprint != run.runtime_config().fingerprint()
                    or checkpoint.context.conversation_id != run.conversation_id
                    or checkpoint.context.user_id != str(run.initiated_by_id)
                ):
                    raise ValidationError("Checkpoint context does not match the run")
                run.checkpoint = checkpoint.model_dump(mode="json")
                run.checkpoint_runtime = checkpoint.runtime
                run.checkpoint_version = checkpoint.format_version
                run.consumed_message_sequence = checkpoint.consumed_message_sequence
                # A checkpoint is a provider-safe boundary for the visible turn.
                run.finish_messages("completed")
            if hasattr(event, "usage"):
                attempt.usage = event.usage.model_dump(mode="json")
                attempt.save()
                totals = RunUsage().model_dump(mode="json")
                for values in run.attempts.values_list("usage", flat=True):
                    usage = RunUsage.model_validate(values)
                    for key in (
                        "input_tokens",
                        "output_tokens",
                        "tool_calls",
                        "duration_seconds",
                    ):
                        totals[key] += getattr(usage, key)
                run.usage = totals
                payload["data"]["usage"] = totals
            if kind in {"run.completed", "run.cancelled", "run.failed", "run.paused"}:
                if run.cancel_requested_at and kind in {"run.completed", "run.paused"}:
                    kind = "run.cancelled"
                attempt.status = kind.split(".")[1]
                attempt.finished_at = timezone.now()
                run.status = "waiting" if kind == "run.paused" else attempt.status
                if kind == "run.paused":
                    payload["data"]["wait_kind"] = event.wait_condition.kind
                    run.wait_condition = event.wait_condition.model_dump(mode="json")
                    run.resume_after = event.resume_after
                else:
                    run.finished_at = timezone.now()
                    run.wait_condition = None
                if kind == "run.failed":
                    run.error = event.error.model_dump(mode="json")
                    attempt.error = run.error
                    payload["data"]["error"] = run.error
                if kind in {"run.failed", "run.cancelled"}:
                    run.stop_pending_tools()
                run.finish_messages(
                    "completed" if kind == "run.completed" else "interrupted"
                )
                attempt.save()
                run.conversation.save(update_fields=["datetime_updated"])
            run.save()
            if kind == "run.paused":
                run.queue_after_approvals()
            # Opaque checkpoints never enter the public event stream.
            return run.append_event(kind, payload, attempt=attempt)
