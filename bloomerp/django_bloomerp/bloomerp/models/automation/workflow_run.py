from django.db import models
from bloomerp.models.automation import workflow
from bloomerp.models.mixins.user_stamp_model_mixin import UserStampModelMixin
from bloomerp.models.mixins import TimestampModelMixin
from django.utils.translation import gettext_lazy as _

class WorkflowRun(
    UserStampModelMixin,
    TimestampModelMixin,
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