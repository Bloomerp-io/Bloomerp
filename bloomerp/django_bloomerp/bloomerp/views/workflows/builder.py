
import json

from bloomerp.automation.registry import WORKFLOW_NODE_REGISTRY
from bloomerp.models.automation.workflow import Workflow
from bloomerp.serializers.workflow import WorkflowSerializer
from bloomerp.router import router
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView


@router.register(
    path="builder",
    name="Builder",
    url_name="builder",
    description="Update a workflow",
    route_type="detail",
    models=[Workflow],
)
class WorkflowBuilderView(BaseBloomerpDetailView):
    model = Workflow
    template_name = "views/workflows/builder.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        workflow = self.object
        ctx["node_types"] = WORKFLOW_NODE_REGISTRY.grouped()
        ctx["workflow_id"] = workflow.id
        ctx["workflow_json"] = json.dumps(WorkflowSerializer(workflow).data)
        return ctx
