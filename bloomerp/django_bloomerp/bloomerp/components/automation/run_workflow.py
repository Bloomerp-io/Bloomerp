from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from bloomerp.models import Workflow
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from django import forms

from bloomerp.utils.requests import render_blank_form, render_message, render_page_refresh_with_message
from bloomerp.widgets.code_editor_widget import CodeEditorWidget

from bloomerp.automation.run import run_workflow as _run_workflow

class RunWorkflowForm(forms.Form):
    data = forms.JSONField(
        label="Trigger data for this workflow",
        widget=CodeEditorWidget(
            language="json"
        )
    )


@router.register(
    path="components/automation/run_workflow/<str:workflow_id>",
    url_name="components_automation_run_workflow"
)
@login_required
def run_workflow(request: HttpRequest, workflow_id: str) -> HttpResponse:
    """Endpoint to run a specific workflow

    Args:
        request (HttpRequest)
        workflow_id (str)

    Returns:
        HttpResponse: for post request, a message containing the result, for get requests.
    """
    workflow = get_object_or_404(Workflow, id=workflow_id)

    if not UserPolicyManager(request.user).has_access_to_object(workflow, BloomerpPermission.CHANGE):
        return HttpResponse(status=403, content="No permission to run this workflow")
    
    # Extract initial data
    trigger=workflow.get_trigger()
    sub_type = trigger.sub_type
    initial_data = trigger.parameters or {}
    
    form = RunWorkflowForm(
        data=request.POST if request.method == "POST" else None,
        initial=initial_data if sub_type == "HUMAN_TRIGGER" else None
    )
    
    if request.method == "POST" and form.is_valid():
        result = _run_workflow(workflow, form.cleaned_data.get("data", {}))
        if not result:
            message = "Workflow starting run"
        else:
            message = f"Workflow ran with status {result.status}"
            
            
        return render_page_refresh_with_message(
            request,
            message=message,
            type="info"
        )
        
    
    return render_blank_form(
        request,
        form,
        reverse("components_automation_run_workflow", kwargs={"workflow_id":workflow.id}),
        submit_label="Run workflow",
        button_attrs={
            "bloomerp-close-modal" : "bloomerp-general-use-modal"
        },
        text="Run this workflow by giving the trigger data."
    )
        
    
        
