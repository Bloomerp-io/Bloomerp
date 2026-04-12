from django.db import models
from bloomerp.models.automation import workflow
from bloomerp.models.mixins import UserStampedModelMixin
from bloomerp.models.mixins import TimestampedModelMixin
from django.utils.translation import gettext_lazy as _

class WorkflowRun(
    UserStampedModelMixin,
    TimestampedModelMixin,
    models.Model):
    
    class Meta:
        db_table = "bloomerp_workflow_run"
        verbose_name = _("Workflow Run")
        verbose_name_plural = _("Workflow Runs")
    
    workflow = models.ForeignKey(
        workflow.Workflow,
        on_delete=models.CASCADE,
        help_text=_("The workflow associated with this run.")
        )