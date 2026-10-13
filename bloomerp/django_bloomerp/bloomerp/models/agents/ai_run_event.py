"""Ordered durable events for replay and execution provenance."""

from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models

from .base import AgentModel
from .fields import AgentJSONField


class AIRunEvent(AgentModel):
    """Append an event to a run, optionally emitted by a particular attempt."""

    immutable_fields = (
        "run_id",
        "attempt_id",
        "sequence",
        "event_type",
        "schema_version",
        "payload",
    )
    run = models.ForeignKey(
        "bloomerp.AIRun", on_delete=models.CASCADE, related_name="events"
    )
    attempt = models.ForeignKey(
        "bloomerp.AIRunAttempt",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="events",
    )
    sequence = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=100)
    schema_version = models.PositiveIntegerField(default=1, choices=[(1, "Version 1")])
    payload = AgentJSONField(schema="event.v1", default=dict, blank=True)

    class Meta(AgentModel.Meta):
        db_table = "bloomerp_ai_run_event"
        ordering: ClassVar[list[str]] = ["sequence"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["run", "sequence"], name="ai_run_event_sequence"
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1), name="ai_event_sequence_positive"
            ),
        ]

    def clean(self) -> None:
        """Prevent attempt references from crossing run boundaries."""
        super().clean()
        if self.attempt_id and self.attempt.run_id != self.run_id:
            raise ValidationError(
                {"attempt": "The event attempt must belong to this run."}
            )
        references = {
            "message_id": ("AIMessage", "conversation_id", self.run.conversation_id),
            "artifact_id": ("AIArtifact", "conversation_id", self.run.conversation_id),
            "tool_call_id": ("AIToolCall", "run_id", self.run_id),
            "approval_id": ("AIApproval", "tool_call__run_id", self.run_id),
        }
        for key, (model_name, owner_field, owner_id) in references.items():
            reference = self.payload.get(key)
            if reference is not None:
                model = self._meta.apps.get_model("bloomerp", model_name)
                if not model.objects.filter(
                    pk=reference, **{owner_field: owner_id}
                ).exists():
                    raise ValidationError(
                        {"payload": f"Invalid or unrelated event reference: {key}."}
                    )

    def public_payload(self) -> dict[str, Any]:
        """Translate one committed public event into the shared chat wire envelope."""
        if self.event_type == "checkpoint.created":
            raise ValueError("Checkpoints are private")
        statuses = {
            "text.delta": "streaming",
            "run.completed": "completed",
            "run.failed": "failed",
            "run.cancelled": "cancelled",
            "run.paused": "paused",
            "usage.updated": "usage",
        }
        return {
            "type": "chat.event",
            "conversation_id": str(self.run.conversation_id),
            "run_id": str(self.run_id),
            "client_message_id": str(self.run.trigger_message_id),
            "sequence": self.sequence,
            "event_type": self.event_type,
            "status": statuses.get(self.event_type, "event"),
            "message_id": self.payload.get("message_id"),
            "delta": self.payload.get("text"),
            "payload": self.payload,
        }
