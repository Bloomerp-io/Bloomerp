from typing import TYPE_CHECKING
from django.db import models
from bloomerp.models.mixins import UserStampedModelMixin
from bloomerp.models.mixins import TimestampedModelMixin
from django.utils.translation import gettext_lazy as _
from bloomerp.automation.defintion import WorkflowNodeType

if TYPE_CHECKING:
    from bloomerp.models.automation.workflow_node import WorkflowNode

class Workflow(
    UserStampedModelMixin,
    TimestampedModelMixin,
    models.Model):
    """
    A workflow is a model for automation.
    Each workflow can have differnent nodes.
    """
    class Meta:
        db_table = "bloomerp_workflow"
        verbose_name = _("Workflow")
        verbose_name_plural = _("Workflows")
    
    name = models.CharField(
        max_length=255,
        help_text=_("The name of the workflow.")
        )
    
    def get_trigger(self) -> "WorkflowNode":
        """Returns the trigger of a workflow.

        Returns:
            WorkflowNode: the triggering node of this workflow
        """
        nodes : models.QuerySet["WorkflowNode"] = self.nodes.all()

        return nodes.filter(
            type=WorkflowNodeType.TRIGGER.value.name
        ).first()