from django.db import models
from bloomerp.models.automation import workflow
from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.models.mixins.absolute_url_model_mixin import AbsoluteUrlModelMixin
from bloomerp.models.mixins.user_stamp_model_mixin import UserStampModelMixin
from bloomerp.models.mixins import TimestampModelMixin
from django.utils.translation import gettext_lazy as _

class WorkflowRun(
    TimestampModelMixin,
    AbsoluteUrlModelMixin,
    models.Model):
    
    class Meta:
        db_table = "bloomerp_workflow_run"
        verbose_name = _("Workflow Run")
        verbose_name_plural = _("Workflow Runs")
    
    bloomerp_config = BloomerpModelConfig(
        module="automation",
        layout=FieldLayout(
            rows=[
                LayoutRow(
                    columns=2,
                    items=[
                        LayoutItem(id="workflow"),
                        LayoutItem(id="datetime_created"),
                        LayoutItem(id="steps", colspan=2)
                    ]
                )
            ]
        )
    )
    
    workflow = models.ForeignKey(
        workflow.Workflow,
        on_delete=models.CASCADE,
        help_text=_("The workflow associated with this run."),
        editable=False,
        related_name="runs",
    )
    
    def __str__(self):
        return f"{self.workflow.name} - {self.datetime_created}"
    