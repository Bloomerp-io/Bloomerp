from django.db import models

from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.models.mixins.timestamp_model_mixin import TimestampModelMixin

class WorkflowRunStepStatus(models.TextChoices):
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


class WorkflowRunStep(TimestampModelMixin, models.Model):
    class Meta:
        db_table = "bloomerp_workflow_run_step"
        verbose_name = "Workflow Run Step"
        verbose_name_plural = "Workflow Run Steps"
    
    bloomerp_config = BloomerpModelConfig(
        module="automation",
    )
    
    workflow_run = models.ForeignKey(
        "WorkflowRun",
        on_delete=models.CASCADE,
        related_name="steps",
        help_text="The workflow run that this step belongs to.",
    )
    sequence = models.PositiveIntegerField(
        help_text="The sequence number of this step within the workflow run.",
    )
    action_id = models.CharField(
        max_length=255,
        help_text="The identifier of the action being executed in this step."
    )
    status = models.CharField(
        max_length=20,
        choices=WorkflowRunStepStatus.choices,
        default=WorkflowRunStepStatus.COMPLETED,
        help_text="The status of this workflow run step.",
    )
    
