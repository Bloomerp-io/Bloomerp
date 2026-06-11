
import json

from bloomerp.automation.defintion import WorkflowNodeType
from bloomerp.models.automation.workflow import Workflow
from bloomerp.serializers.workflow import WorkflowSerializer
from bloomerp.router import router
from bloomerp.views.detail.base_detail import BaseBloomerpDetailView


@router.register(
    path="builder",
    name="Builder",
    url_name="builder",
    description="Update a workflow",
    route_type="detail",
    models=[Workflow],
)
class CreateWorkflowView(BaseBloomerpDetailView):
    model = Workflow
    template_name = "cotton/workflow.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        workflow = self.object
        ctx["node_types"] = [nt for nt in WorkflowNodeType]
        ctx["workflow_id"] = workflow.id
        ctx["workflow_json"] = json.dumps(WorkflowSerializer(workflow).data)
        return ctx
