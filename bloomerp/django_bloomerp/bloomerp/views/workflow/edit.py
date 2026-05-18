
from bloomerp.models.automation.workflow import Workflow
from bloomerp.views.base import BaseBloomerpView
from django.views.generic import TemplateView
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
    
    
