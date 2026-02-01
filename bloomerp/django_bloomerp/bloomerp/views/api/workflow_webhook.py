from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from bloomerp.models.automation.workflow import Workflow
from bloomerp.services.workflow_services import run_workflow


def workflow_webhook(request:HttpRequest, workflow_id:str) -> HttpResponse:
    
    # Get the workflow
    workflow = get_object_or_404(Workflow, id=workflow_id)
    
    # Get the data
    data = request.POST
    
    # Run the actual workflow
    run_workflow(workflow, data)
    
    