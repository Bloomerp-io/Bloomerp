"""Stable tool-call identities and approval proposal fingerprints."""

import hashlib
import json
import uuid
from typing import TYPE_CHECKING, ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from pydantic import JsonValue

from bloomerp.agents.definition import ProposalSnapshot

from .base import AgentModel
from .fields import AgentJSONField

if TYPE_CHECKING:
    from bloomerp.agents.runtime import (
        AgentRuntimeToolOutcome,
        AgentRuntimeToolProposal,
    )

    from .ai_run import AIRun


def proposal_fingerprint(proposal: dict[str, JsonValue]) -> str:
    """Hash canonical proposal JSON including tool version and exact arguments."""
    normalized = ProposalSnapshot.model_validate(proposal).model_dump(mode="json")
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class AIToolCall(AgentModel):
    """Track a logical tool action independently of executor retries."""

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        WAITING = "waiting", "Waiting for approval"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        UNKNOWN = "unknown", "Outcome requires reconciliation"

    immutable_fields = (
        "run_id",
        "tool_identifier",
        "tool_version",
        "provider_call_id",
        "idempotency_key",
        "arguments",
        "proposal_hash",
    )
    run = models.ForeignKey(
        "bloomerp.AIRun", on_delete=models.CASCADE, related_name="tool_calls"
    )
    first_dispatch_attempt = models.ForeignKey(
        "bloomerp.AIRunAttempt",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="first_dispatched_tool_calls",
    )
    tool_identifier = models.CharField(max_length=255)
    tool_version = models.CharField(max_length=100)
    provider_call_id = models.CharField(max_length=255)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PROPOSED
    )
    arguments = AgentJSONField(default=dict, blank=True)
    proposal_hash = models.CharField(max_length=64, editable=False, blank=True)
    result = AgentJSONField(null=True, blank=True)
    error = AgentJSONField(schema="error.v1", null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def display_title(self) -> str:
        """Return the registered MCP title for this tool, falling back to its identifier."""
        from bloomerp.router import router

        for route in router.get_mcp_routes():
            if route.url_name == self.tool_identifier:
                return route.mcp.title or route.name or self.tool_identifier
        return self.tool_identifier

    class Meta(AgentModel.Meta):
        db_table = "bloomerp_ai_tool_call"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["run", "provider_call_id"], name="ai_tool_provider_call"
            )
        ]

    def immutable_fields_for(self, old: AgentModel) -> tuple[str, ...]:
        """Allow the first dispatch to be set once without rewriting its history."""
        if old.first_dispatch_attempt_id is not None:
            return self.immutable_fields + ("first_dispatch_attempt_id",)
        return self.immutable_fields

    def clean(self) -> None:
        """Bind dispatch to the same run and derive the immutable proposal hash."""
        super().clean()
        if (
            self.first_dispatch_attempt_id
            and self.first_dispatch_attempt.run_id != self.run_id
        ):
            raise ValidationError(
                {
                    "first_dispatch_attempt": "The dispatch attempt must belong to this run."
                }
            )
        self.proposal_hash = proposal_fingerprint(
            {
                "tool_identifier": self.tool_identifier,
                "tool_version": self.tool_version,
                "arguments": self.arguments,
            }
        )

    @classmethod
    def prepare(
        cls,
        run: "AIRun",
        lease_token: uuid.UUID,
        proposal: "AgentRuntimeToolProposal",
        *,
        requires_approval: bool,
    ) -> tuple["AIToolCall", bool]:
        """Serialize proposal identity, approval and dispatch ownership under the run lease."""
        from django.utils import timezone

        from .ai_approval import AIApproval

        with run.locked() as current:
            attempt = current.leased_attempt(lease_token)
            if current.cancel_requested_at:
                raise ValidationError("Run cancellation requested")
            tool, _created = cls.objects.get_or_create(
                run=current,
                provider_call_id=proposal.provider_call_id,
                defaults={
                    "tool_identifier": proposal.tool_identifier,
                    "tool_version": proposal.tool_version,
                    "arguments": proposal.arguments,
                },
            )
            expected = proposal_fingerprint(
                {
                    "tool_identifier": proposal.tool_identifier,
                    "tool_version": proposal.tool_version,
                    "arguments": proposal.arguments,
                }
            )
            if tool.proposal_hash != expected:
                raise ValidationError("Provider call identity has changed")
            if tool.status == "running":
                # A previous dispatch may have committed externally before losing its result.
                tool.status = "unknown"
                tool.save()
                return tool, False
            if tool.status not in {"proposed", "waiting"}:
                return tool, False
            if requires_approval and not tool.approvals.exists():
                AIApproval.objects.create(
                    tool_call=tool,
                    requirement_snapshot={
                        "rule_key": "agent.tool",
                        "rule_version": "1",
                        "mode": "conversation_owner",
                    },
                    proposal_snapshot={
                        "tool_identifier": tool.tool_identifier,
                        "tool_version": tool.tool_version,
                        "arguments": tool.arguments,
                    },
                )
                tool.status = "waiting"
                tool.save()
            approvals = list(tool.approvals.all())
            if any(
                item.status in {"rejected", "cancelled", "expired"}
                or (item.expires_at and item.expires_at <= timezone.now())
                for item in approvals
            ):
                tool.status, tool.finished_at = "rejected", timezone.now()
                tool.save()
                return tool, False
            if any(item.status == "pending" for item in approvals):
                return tool, False
            tool.status = "running"
            tool.first_dispatch_attempt = attempt
            tool.started_at = timezone.now()
            tool.save()
            return tool, True

    def complete(self, result: dict[str, JsonValue], lease_token: uuid.UUID) -> None:
        """Store the unmodified MCP result only while this executor still owns the run."""
        from django.utils import timezone

        with self.run.locked() as run:
            run.leased_attempt(lease_token)
            self.refresh_from_db()
            if self.status != "running":
                raise ValidationError("Tool dispatch is no longer current")
            self.result = result
            self.status = "failed" if result.get("isError") else "completed"
            self.finished_at = timezone.now()
            self.save()

    def mark_unknown(self, lease_token: uuid.UUID) -> None:
        """Record an uncertain outcome without claiming rollback or scheduling a retry."""
        with self.run.locked() as run:
            run.leased_attempt(lease_token)
            self.refresh_from_db()
            self.status = "unknown"
            self.save()

    def runtime_outcome(self) -> "AgentRuntimeToolOutcome":
        """Return exact MCP results, or a durable wait/rejection/reconciliation outcome."""
        from bloomerp.agents.definition import AgentError
        from bloomerp.agents.runtime import AgentRuntimeToolOutcome

        identity = {"tool_call_id": self.pk, "provider_call_id": self.provider_call_id}
        if self.status == "waiting":
            return AgentRuntimeToolOutcome(
                **identity,
                status="waiting",
                approval_ids=tuple(
                    self.approvals.filter(status="pending").values_list("pk", flat=True)
                ),
            )
        if self.status in {"completed", "failed"} and self.result is not None:
            # MCP isError is an executed tool result, not a transport exception.
            return AgentRuntimeToolOutcome(
                **identity, status="completed", result=self.result
            )
        return AgentRuntimeToolOutcome(
            **identity,
            status="rejected" if self.status == "rejected" else "failed",
            error=AgentError(
                code="approval_rejected"
                if self.status == "rejected"
                else "tool_outcome_unknown",
                message="Action was not approved."
                if self.status == "rejected"
                else "The previous action's outcome is unknown. Do not repeat it; reconcile it first.",
            ),
        )
