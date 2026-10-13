"""Explicit approval requirements and immutable decisions on exact proposals."""

from typing import TYPE_CHECKING, ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .ai_tool_call import proposal_fingerprint
from .base import AgentModel
from .fields import AgentJSONField

if TYPE_CHECKING:
    from bloomerp.models.users.user import AbstractBloomerpUser

    from .ai_run_event import AIRunEvent


class AIApproval(AgentModel):
    """Record who may approve a proposal and who actually decided it."""

    class Meta(AgentModel.Meta):
        db_table = "bloomerp_ai_approval"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "expires_at"], name="ai_approval_expiry")
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=["approved", "rejected"],
                        decided_by__isnull=False,
                        decided_at__isnull=False,
                    )
                    | models.Q(
                        status__in=["pending", "expired", "cancelled"],
                        decided_by__isnull=True,
                        decided_at__isnull=True,
                    )
                ),
                name="ai_approval_decision_actor",
            ),
        ]

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    immutable_fields = (
        "tool_call_id",
        "required_approver_id",
        "requirement_snapshot",
        "proposal_snapshot",
        "proposal_hash",
        "expires_at",
    )
    tool_call = models.ForeignKey(
        "bloomerp.AIToolCall", on_delete=models.CASCADE, related_name="approvals"
    )
    required_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="assigned_ai_approvals",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="decided_ai_approvals",
    )
    requirement_snapshot = AgentJSONField(schema="approval_requirement.v1")
    proposal_snapshot = AgentJSONField(schema="proposal.v1")
    proposal_hash = models.CharField(max_length=64, editable=False, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    reason = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    def immutable_fields_for(self, old: AgentModel) -> tuple[str, ...]:
        """Freeze a terminal decision while allowing a pending approval to resolve."""
        if old.status != self.Status.PENDING:
            return self.immutable_fields + (
                "status",
                "decided_by_id",
                "decided_at",
                "reason",
            )
        return self.immutable_fields

    def clean(self) -> None:
        """Ensure the proposal, assignment, decision actor, and expiry agree."""
        super().clean()
        self.proposal_hash = proposal_fingerprint(self.proposal_snapshot)
        if self.tool_call_id and self.proposal_hash != self.tool_call.proposal_hash:
            raise ValidationError(
                {
                    "proposal_snapshot": "Approval must match the tool call's exact proposal."
                }
            )
        if (
            self.requirement_snapshot["mode"] == "assigned_user"
            and not self.required_approver_id
        ):
            raise ValidationError(
                {"required_approver": "Assigned-user approval requires an assignee."}
            )
        if self.status in {self.Status.APPROVED, self.Status.REJECTED}:
            if not self.decided_by_id or not self.decided_at:
                raise ValidationError("A decision requires an actor and timestamp.")
            if (
                self.required_approver_id
                and self.decided_by_id != self.required_approver_id
            ):
                raise ValidationError(
                    {"decided_by": "Only the assigned approver may decide."}
                )
            if (
                self.requirement_snapshot["mode"] == "conversation_owner"
                and self.decided_by_id != self.tool_call.run.conversation.owner_id
            ):
                raise ValidationError(
                    {"decided_by": "This approval requires the conversation owner."}
                )
            if self.expires_at and self.decided_at >= self.expires_at:
                raise ValidationError(
                    {
                        "decided_at": "An expired proposal cannot be approved or rejected."
                    }
                )

    def decide(
        self, user: "AbstractBloomerpUser", decision: str, reason: str = ""
    ) -> "AIRunEvent | None":
        """Serialize eligible decisions against cancellation, expiry and the exact proposal."""
        from django.core.exceptions import PermissionDenied
        from django.utils import timezone

        with self.tool_call.run.locked() as run:
            self.refresh_from_db()
            if user.pk != run.conversation.owner_id or not user.is_active:
                raise PermissionDenied("Approval access denied")
            if self.requirement_snapshot["mode"] != "conversation_owner":
                raise PermissionDenied(
                    "This executor only supports conversation-owner approvals"
                )
            if self.status == decision and self.decided_by_id == user.pk:
                return None
            if run.status not in {"running", "waiting"} or run.cancel_requested_at:
                raise ValidationError("Run is no longer awaiting a decision")
            if self.status != "pending" or decision not in {"approved", "rejected"}:
                raise ValidationError("Approval is no longer pending")
            self.status, self.reason = decision, reason
            self.decided_by, self.decided_at = user, timezone.now()
            self.save()
            event = run.append_event(
                "approval.decided",
                {
                    "tool_call_id": str(self.tool_call_id),
                    "approval_id": str(self.pk),
                    "data": {"status": decision, "reason": reason},
                },
            )
            run.queue_after_approvals()
            return event
