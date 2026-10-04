"""Declarative lifecycle scenarios for AIApproval persistence."""

from datetime import timedelta
from functools import partial
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone

from bloomerp.models.agents import AIApproval
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)

from ._fixtures import AgentModelFixtures


class TestAiapprovalModel(AgentModelFixtures, BloomerpModelTestCase):
    """Exercise proposal binding, decision actors, expiry, and finality."""

    model = AIApproval

    def get_test_scenarios(self) -> list[ModelScenario[AIApproval]]:
        """Declare each approval decision as a separate lifecycle scenario."""
        return self.with_agent_fixtures(
            [
                ModelScenario(
                    name="Decision method is idempotent and publishes one durable event",
                    create_args=self.running_approval_args,
                    create_validators=self.decision_method_is_idempotent,
                ),
                ModelScenario(
                    name="Owner approves the exact proposal",
                    create_args=self.pending_args,
                    create_validators=self.proposal_matches,
                    update_args=self.owner_decision,
                    update_validators=self.owner_decision_is_persisted,
                ),
                ModelScenario(
                    name="Changed proposal is rejected",
                    create_args=partial(
                        self.pending_args,
                        proposal_snapshot={
                            "tool_identifier": "navigate",
                            "tool_version": "1",
                            "arguments": {"path": "/changed/"},
                        },
                    ),
                    expected_exceptions=[
                        ExpectedModelException(
                            "create", ValidationError, "exact proposal"
                        )
                    ],
                ),
                ModelScenario(
                    name="Another user cannot decide owner approval",
                    create_args=self.pending_args,
                    update_args=self.foreign_decision,
                    expected_exceptions=[
                        ExpectedModelException(
                            "update", ValidationError, "conversation owner"
                        )
                    ],
                ),
                ModelScenario(
                    name="Final approval cannot be reversed",
                    create_args=self.approved_args,
                    create_validators=self.owner_decision_is_persisted,
                    update_args={"status": "rejected"},
                    expected_exceptions=[
                        ExpectedModelException("update", ValidationError, "immutable")
                    ],
                ),
                ModelScenario(
                    name="Assigned approval requires an assignee",
                    create_args=partial(
                        self.pending_args,
                        requirement_snapshot={
                            "rule_key": "manager",
                            "rule_version": "1",
                            "mode": "assigned_user",
                        },
                    ),
                    expected_exceptions=[
                        ExpectedModelException("create", ValidationError, "assignee")
                    ],
                ),
                ModelScenario(
                    name="Expired approval cannot be decided",
                    create_args=self.expired_args,
                    update_args=self.owner_decision,
                    expected_exceptions=[
                        ExpectedModelException("update", ValidationError, "expired")
                    ],
                ),
            ]
        )

    def running_approval_args(self) -> dict[str, Any]:
        """Build an approval while the originating executor is still running."""
        return self.approval_args(self.make_tool(self.make_run(status="running")))

    def decision_method_is_idempotent(self, approval: AIApproval) -> bool:
        """Verify retries retain the exact actor, decision and single event identity."""
        event = approval.decide(self.user, "approved", "Reviewed")
        repeated = approval.decide(self.user, "approved", "Reviewed")
        approval.refresh_from_db()
        return (
            event is not None
            and repeated is None
            and approval.status == "approved"
            and approval.decided_by_id == self.user.pk
            and approval.tool_call.run.events.filter(
                event_type="approval.decided"
            ).count()
            == 1
        )

    def pending_args(self, **overrides: Any) -> dict[str, Any]:
        """Prepare a fresh proposal and its pending owner approval."""
        return self.approval_args(self.make_tool(self.make_run()), **overrides)

    def owner_decision(self) -> dict[str, Any]:
        """Supply the authorized actor and timestamp for an approval decision."""
        return {
            "status": "approved",
            "decided_by": self.user,
            "decided_at": timezone.now(),
        }

    def foreign_decision(self) -> dict[str, Any]:
        """Attempt the same decision using a different actor."""
        return self.owner_decision() | {"decided_by": self.other_user}

    def approved_args(self) -> dict[str, Any]:
        """Create a final approval so the framework can attempt its reversal."""
        return self.pending_args(**self.owner_decision())

    def expired_args(self) -> dict[str, Any]:
        """Create a still-pending proposal whose decision deadline has passed."""
        return self.pending_args(expires_at=timezone.now() - timedelta(minutes=1))

    def proposal_matches(self, approval: AIApproval) -> bool:
        """Verify the stored fingerprint binds the exact underlying proposal."""
        return approval.proposal_hash == approval.tool_call.proposal_hash

    def owner_decision_is_persisted(self, approval: AIApproval) -> bool:
        """Verify final status, actor, timestamp, and proposal after a database read."""
        return (
            approval.status == "approved"
            and approval.decided_by_id == self.user.pk
            and approval.decided_at is not None
            and self.proposal_matches(approval)
        )
