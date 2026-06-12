from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from numpy import tri
from bloomerp.models.automation.workflow import Workflow
from bloomerp.services.workflow_services import run_workflow
from bloomerp.router import router

@router.register(
    path="api/webhook/<str:workflow_id>/",
    url_name="api_workflow_webhook",
)
def workflow_webhook(request:HttpRequest, workflow_id:str) -> HttpResponse:
    """
    Args:
        request (HttpRequest): The HTTP request object.
        workflow_id (str): The ID of the workflow to be triggered.

    Returns:
        HttpResponse: The HTTP response indicating the result of the workflow execution.
    """
    # TODO: Authentication
    
    # Get the workflow
    workflow = get_object_or_404(Workflow, id=workflow_id)
    
    # Get the trigger
    trigger = workflow.get_trigger()
    
    if not trigger or trigger.node_sub_type_id != "WEBHOOK_TRIGGER":
        return HttpResponse("Invalid workflow trigger", status=400)
    
    # Get the payload from the request body
    try:
        payload = request.body.decode("utf-8")
    except Exception as e:
        return HttpResponse(f"Invalid payload: {str(e)}", status=400)
    
    # Run the workflow with the payload as trigger data
    if workflow.run_asynchronously:
        run_workflow(workflow=workflow, trigger_data={"payload": payload})
        
        return JsonResponse(
            {
                "status": "Workflow queued for asynchronous execution.",
                "workflow_id": workflow_id,
            },
        )
        
    workflow_run = run_workflow(workflow=workflow, trigger_data={"payload": payload})
    
    
    
    
    
    
    
    