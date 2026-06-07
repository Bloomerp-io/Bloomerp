from typing import TYPE_CHECKING
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import BloomerpModelConfig, DetailViewSettings, ObjectAction
from bloomerp.models.mixins.absolute_url_model_mixin import AbsoluteUrlModelMixin
from bloomerp.models.mixins.user_stamp_model_mixin import UserStampModelMixin
from bloomerp.models.mixins import TimestampModelMixin
from django.utils.translation import gettext_lazy as _
from bloomerp.automation.defintion import WorkflowNodeType
from bloomerp.utils.requests import render_message

if TYPE_CHECKING:
    from bloomerp.models.automation.workflow_node import WorkflowNode
    from bloomerp.models.automation.workflow_edge import WorkflowEdge


def _run_workflow(request:HttpRequest, object:"Workflow") -> HttpResponse:
    from bloomerp.services.workflow_services import format_execution_trace, run_workflow
    import traceback
    try:
        workflow_run = run_workflow(object, {})
    except Exception as e:
        traceback.print_exc()
        return render_message(
            request,
            str(e),
            "error"
        )

    trace = format_execution_trace(workflow_run.execution_trace)
    message = f"Workflow run completed. {trace}" if trace else "Workflow run completed."
    return render_message(request, message, "success")


def _is_human_trigger_workflow(request, object:"Workflow") -> bool:
    return object.get_trigger().node_sub_type_id == "HUMAN_TRIGGER"
    

class Workflow(
    UserStampModelMixin,
    TimestampModelMixin,
    AbsoluteUrlModelMixin,
    models.Model
    ):
    """
    A workflow is a model for automation.
    Each workflow can have differnent nodes.
    """
    class Meta:
        db_table = "bloomerp_workflow"
        verbose_name = _("Workflow")
        verbose_name_plural = _("Workflows")
    
    bloomerp_config = BloomerpModelConfig(
        layout=FieldLayout(
            rows=[
                LayoutRow(
                    title="Details",
                    columns=2,
                    items=[
                        LayoutItem(id="name")
                    ]
                ),
                LayoutRow(
                    title="Configuration",
                    columns=2,
                    items=[
                        LayoutItem(id="run_asynchronously")
                    ]
                ),
                
            ]
        ),
        object_actions=[
            ObjectAction(
                id="run_workflow",
                label="Run workflow",
                execution_func=_run_workflow,
                should_render_func=_is_human_trigger_workflow
            )
        ],
        create_redirect_url_func=lambda x: reverse(
            "workflows_detail_builder",
            kwargs={"pk":x.pk}
        ),
        detail_view_settings=DetailViewSettings(
            skip_views=["document_templates", "files"]
        )
    )
    
    name = models.CharField(
        max_length=255,
        help_text=_("The name of the workflow.")
        )
    run_asynchronously = models.BooleanField(
        default=False,
        help_text=_("Whether runs asynchronously")
    )
    
    def get_trigger(self) -> "WorkflowNode":
        """Returns the trigger of a workflow.

        Returns:
            WorkflowNode: the triggering node of this workflow
        """
        nodes: models.QuerySet["WorkflowNode"] = self.nodes.all()

        return nodes.filter(
            type=WorkflowNodeType.TRIGGER.value.id
        ).first()

    def __str__(self) -> str:
        return self.name    
        
    
