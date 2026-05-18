
from bloomerp.models.automation.workflow import Workflow
from bloomerp.views.base import BaseBloomerpView
from django.views.generic import TemplateView
from bloomerp.router import router


@router.register(
    path="create",
    name="Create {model}",
    url_name="add",
    description="Create a new object from {model}",
    route_type="model",
    models=[Workflow],
)
class CreateWorkflowView(BaseBloomerpView, TemplateView):
    model = Workflow
    template_name = "cotton/workflow.html"
    
    
