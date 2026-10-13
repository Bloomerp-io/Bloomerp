"""Individual execution periods of durable runs."""

from typing import ClassVar

from django.db import models

from .base import AgentModel
from .fields import AgentJSONField


class AIRunAttempt(AgentModel):
    """Record a leased inline or worker execution, ending on pause or termination."""

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        ABANDONED = "abandoned", "Abandoned"

    class ExecutionMode(models.TextChoices):
        INLINE = "inline", "Inline"
        WORKER = "worker", "Worker"

    immutable_fields = ("run_id", "number", "execution_mode", "lease_token")
    run = models.ForeignKey(
        "bloomerp.AIRun", on_delete=models.CASCADE, related_name="attempts"
    )
    number = models.PositiveIntegerField()
    execution_mode = models.CharField(max_length=16, choices=ExecutionMode.choices)
    executor_id = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.RUNNING
    )
    lease_token = models.UUIDField(unique=True)
    lease_expires_at = models.DateTimeField()
    heartbeat_at = models.DateTimeField()
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    usage = AgentJSONField(schema="usage.v1", default=dict, blank=True)
    error = AgentJSONField(schema="error.v1", null=True, blank=True)

    class Meta(AgentModel.Meta):
        db_table = "bloomerp_ai_run_attempt"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["run", "number"], name="ai_attempt_number"),
            models.UniqueConstraint(
                fields=["run"],
                condition=models.Q(status="running"),
                name="ai_one_active_attempt",
            ),
            models.CheckConstraint(
                condition=models.Q(number__gte=1), name="ai_attempt_number_positive"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["status", "lease_expires_at"], name="ai_attempt_expiry"
            )
        ]
